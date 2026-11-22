"""E10: how many dimensions does a concept without a unit occupy?

Some concepts are no unit's job: composition, physico-chemistry, length, localization and taxonomy. For each such family
of related targets, a ridge readout from a pooled representation to all of the family's targets is fitted on training
proteins, with its penalty chosen on validation proteins, and then cut to rank r, for r of 1, 2, 4, 8 and 16, by
projecting it on the top r directions of its fitted values (reduced-rank ridge regression; Mukherjee and Zhu, 2011). A
family's dimension is the smallest r whose validation score reaches 95% of the full readout's, both measured above
chance; the stable rank of the full readout's validation predictions is reported beside it. Readouts read the mean-pooled
products z and the mean-pooled output stream at each depth of an extraction (`concepts.ConceptExtraction`).

Families from the concept tasks: ProtParam's 20 amino-acid percentages (composition) and nine physico-chemical values,
standardized on training proteins and scored by mean R squared; length in ten bins at the training quantiles of its
logarithm, and localization's classes, as indicator columns scored by mean one-against-rest ROC AUC. Taxonomy comes from
a panel of atlas training proteins, one a cluster, with lineages from the compendium's eight ranks: two proteins' distance is the
path between their lineages in the NCBI taxonomy, the targets are the 32 classical multidimensional scaling coordinates
of the fit proteins' distances, and a readout is scored by Spearman's rho between the distances of its predictions and
the lineage distances over every pair of validation or test proteins.

Co-firing blocks ask whether a concept family that no unit carries is carried by a few units that fire together, as
block-sparse featurizers propose (Fel et al., 2026). ESMC-600's native poles at block 26 are clustered by average linkage
on one minus their correlation over E8's residues and cut where merged poles correlate below 0.5 on average; each block
of 2 to 64 poles reads each concept family through a ridge readout on its mean-pooled poles, the block with the best
validation R squared is scored on test proteins by the family's metric, and the null redraws every tested block as random
poles of the same size 20 times and repeats the selection.

Symbols: n proteins; w features; k retained spectral directions; t targets; r rank; p poles; b blocks; s block size.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.linalg
import scipy.sparse as sp
import torch

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from scipy import stats
from scipy.cluster import hierarchy
from scipy.spatial.distance import pdist, squareform
from torch import Tensor

from .concepts import ConceptProteins, ConceptTask, read_feature
from .sparse_probes import column_auroc


RANKS = (1, 2, 4, 8, 16)
PENALTIES = tuple(10.0 ** power for power in range(-1, 8))  # ridge weights on the summed squared loss
SHARE = 0.95
CHANCE = {"r2": 0.0, "auroc": 0.5, "spearman": 0.0}
FEATURES = ("z_mean", "stream_mean")
SPLITS = ("train", "validation", "test")
MIN_CLASS = 5  # positives and negatives an indicator column needs in every split
LENGTH_BINS = 10
COMPOSITION = tuple(f"percent_{letter}" for letter in "acdefghiklmnpqrstvwy")
PHYSICOCHEMICAL = ("fraction_helix_aas", "fraction_turn_aas", "fraction_sheet_aas", "instability_index", "gravy",
                   "isoelectric_point", "charge_at_ph4_7", "charge_at_ph7_2", "charge_at_ph8")
PANEL_PROTEINS = 12_000
PANEL_SHARES = (0.6, 0.2, 0.2)  # fit, validation and test shares of the taxonomy panel
TAXONOMIC_RANKS = ("domain", "kingdom", "phylum", "class", "order", "family", "genus", "species")  # the lineage table's
MDS_DIMENSIONS = 32
SEED = 24895
BLOCK_CORRELATION = 0.5  # average-linkage cut: merged poles correlate at least this on average
BLOCK_SIZES = (2, 64)  # the smallest and largest block read
BLOCK_PENALTY = 1.0  # ridge weight of a block readout on standardized poles
NULL_DRAWS = 20
CHUNK_ELEMENTS = 2**26  # gathered training values per batch of block readouts


@dataclass(frozen=True)
class Family:
    name: str
    metric: str  # "r2", "auroc" or "spearman"
    source: str  # the extraction its rows index: "concepts" or "panel"
    task: str  # whose splits the rows follow; families of one task share a readout's spectral directions
    rows: dict[str, np.ndarray]  # split -> each protein's row in the extraction
    values: dict[str, np.ndarray]  # split -> (n_split, t) targets; taxonomy has training targets only
    pairs: dict[str, np.ndarray] | None = None  # taxonomy: held-out split -> condensed lineage distances, (n(n-1)/2,)

    @property
    def targets(self) -> int:
        return self.values["train"].shape[1]


@dataclass(frozen=True)
class TaxonomyPanel:
    accessions: tuple[str, ...]
    sequences: tuple[str, ...]
    lineages: tuple[tuple[int, ...], ...]  # taxon ids from the root down
    split: np.ndarray  # (n,) "train", "validation" or "test"


def _indicators(labels: Mapping[str, np.ndarray], classes: int) -> dict[str, np.ndarray]:
    """One indicator column per class, keeping the classes with `MIN_CLASS` positives and negatives in every split."""
    # labels: (n_split,) int by split
    columns = {split: labels[split][:, None] == np.arange(classes)[None, :] for split in SPLITS}  # (n_split, classes)
    keep = np.ones(classes, dtype=bool)  # (classes,)
    for values in columns.values():
        positives = values.sum(axis=0)  # (classes,)
        keep &= (positives >= MIN_CLASS) & (len(values) - positives >= MIN_CLASS)
    return {split: values[:, keep] for split, values in columns.items()}  # (n_split, kept)


def concept_families(tasks: Mapping[str, ConceptTask], proteins: ConceptProteins) -> list[Family]:
    """Composition, physico-chemistry and length from ProtParam, and localization's classes."""
    protparam = tasks["prot_param"]
    column = {name: index for index, name in enumerate(protparam.label_names)}
    values = {split: np.stack(frame["label"].to_numpy()).astype(np.float64) for split, frame in protparam.frames.items()}
    families = []
    for name, chosen in (("composition", COMPOSITION), ("physicochemistry", PHYSICOCHEMICAL)):
        picked = {split: array[:, [column[label] for label in chosen]] for split, array in values.items()}  # (n_split, t)
        mean, scale = picked["train"].mean(axis=0), picked["train"].std(axis=0)  # (t,), (t,)
        families.append(Family(name, "r2", "concepts", "prot_param", proteins.rows["prot_param"],
                               {split: (array - mean) / scale for split, array in picked.items()}))
    logarithm = {split: np.log(array[:, column["length"]]) for split, array in values.items()}  # (n_split,)
    edges = np.quantile(logarithm["train"], np.linspace(0, 1, LENGTH_BINS + 1)[1:-1])  # (LENGTH_BINS - 1,)
    bins = {split: np.searchsorted(edges, array, side="right") for split, array in logarithm.items()}  # (n_split,)
    families.append(Family("length", "auroc", "concepts", "prot_param", proteins.rows["prot_param"],
                           _indicators(bins, LENGTH_BINS)))
    localization = tasks["localization"]
    classes = {split: frame["label"].to_numpy().astype(np.int64) for split, frame in localization.frames.items()}  # (n_split,)
    families.append(Family("localization", "auroc", "concepts", "localization", proteins.rows["localization"],
                           _indicators(classes, len(localization.label_names))))
    return families


def rank_lineages(table: pd.DataFrame) -> dict[str, tuple[int, ...]]:
    """Each protein's lineage from the release's lineage table (`protein_id` and `TAXONOMIC_RANKS`): its taxa at the
    ranks where all its organisms agree, from the root down, a rank without one skipped."""
    ranks = table[list(TAXONOMIC_RANKS)].to_numpy(dtype=np.float64)  # (n, 8), NaN where the organisms disagree
    return {str(protein): tuple(int(taxon) for taxon in row[np.isfinite(row)])
            for protein, row in zip(table["protein_id"], ranks, strict=True)}


def taxonomy_panel(atlas: pd.DataFrame, lineages: Mapping[str, Sequence[int]], *, proteins: int = PANEL_PROTEINS,
                   shares: Sequence[float] = PANEL_SHARES, seed: int = SEED) -> TaxonomyPanel:
    """One training protein from each of `proteins` atlas clusters with a lineage, drawn with `seed` and dealt in that
    order into fit, validation and test shares; one protein a cluster keeps the three cluster-disjoint."""
    train = atlas[(atlas["split"] == "train") & atlas["accession"].map(lambda accession: len(lineages.get(accession, ())) > 0)]
    order = np.random.default_rng(seed).permutation(len(train))  # (n_train,)
    chosen = train.iloc[order].drop_duplicates("cluster").head(proteins)
    if len(chosen) < proteins:
        raise ValueError(f"The atlas set has {len(chosen)} training clusters with a lineage, fewer than {proteins}.")
    bounds = np.cumsum([round(share * proteins) for share in shares[:-1]])  # (2,)
    split = np.full(proteins, "test", dtype=object)  # (n,)
    split[:bounds[0]], split[bounds[0]:bounds[1]] = "train", "validation"
    return TaxonomyPanel(tuple(chosen["accession"]), tuple(chosen["sequence"]),
                         tuple(tuple(int(taxon) for taxon in lineages[accession]) for accession in chosen["accession"]), split)


def lineage_distances(first: Sequence[Sequence[int]], second: Sequence[Sequence[int]]) -> np.ndarray:
    """Path lengths in the taxonomy between every lineage of `first` and of `second`: a lineage is a path from the root,
    so two share exactly their common ancestors and the path between them has |a| + |b| - 2 |a & b| edges."""
    taxa = {taxon: column for column, taxon in enumerate(sorted({taxon for lineage in (*first, *second) for taxon in lineage}))}

    def incidence(lineages: Sequence[Sequence[int]]) -> sp.csr_matrix:
        rows = np.repeat(np.arange(len(lineages)), [len(lineage) for lineage in lineages])  # (nnz,)
        columns = np.array([taxa[taxon] for lineage in lineages for taxon in lineage], dtype=np.int64)  # (nnz,)
        return sp.csr_matrix((np.ones(len(rows)), (rows, columns)), shape=(len(lineages), len(taxa)))  # (n, taxa)

    left, right = incidence(first), incidence(second)
    shared = (left @ right.T).toarray()  # (n_first, n_second)
    sizes = np.asarray(left.sum(axis=1)).ravel(), np.asarray(right.sum(axis=1)).ravel()  # (n_first,), (n_second,)
    return sizes[0][:, None] + sizes[1][None, :] - 2 * shared  # (n_first, n_second)


def mds_coordinates(distances: np.ndarray, dimensions: int = MDS_DIMENSIONS) -> np.ndarray:
    """Classical multidimensional scaling: the top `dimensions` coordinates of the double-centered squared distances."""
    # distances: (n, n)
    squared = distances.astype(np.float64) ** 2  # (n, n)
    centered = -0.5 * (squared - squared.mean(axis=0)[None, :] - squared.mean(axis=1)[:, None] + squared.mean())  # (n, n)
    size = len(centered)
    values, vectors = scipy.linalg.eigh(centered, subset_by_index=[size - dimensions, size - 1])  # (m,), (n, m) ascending
    if (values <= 0).any():
        raise ValueError(f"The distances have fewer than {dimensions} positive scaling dimensions.")
    return vectors[:, ::-1] * np.sqrt(values[::-1])[None, :]  # (n, m)


def taxonomy_family(panel: TaxonomyPanel, *, dimensions: int = MDS_DIMENSIONS) -> Family:
    """The taxonomy family of a panel: scaling coordinates of the fit proteins as targets, held-out lineage distances."""
    rows = {split: np.flatnonzero(panel.split == split) for split in SPLITS}  # (n_split,) each
    lineages = {split: [panel.lineages[row] for row in index] for split, index in rows.items()}
    coordinates = mds_coordinates(lineage_distances(lineages["train"], lineages["train"]), dimensions)  # (n_train, m)
    pairs = {split: squareform(lineage_distances(lineages[split], lineages[split]).astype(np.float64), checks=False)
             for split in ("validation", "test")}  # (n(n-1)/2,) each
    return Family("taxonomy", "spearman", "panel", "panel", rows, {"train": coordinates}, pairs)


def family_score(predicted: np.ndarray, family: Family, split: str) -> float:
    """A family's score of predictions for the proteins of one held-out split."""
    # predicted: (n_split, t)
    if family.metric == "spearman":
        score = stats.spearmanr(pdist(predicted), family.pairs[split]).statistic
    elif family.metric == "auroc":
        score = column_auroc(predicted, family.values[split]).mean()
    else:
        truth = family.values[split]  # (n_split, t)
        residual = ((truth - predicted) ** 2).sum(axis=0)  # (t,)
        total = ((truth - truth.mean(axis=0)) ** 2).sum(axis=0)  # (t,)
        score = (1 - residual / total).mean()
    if not np.isfinite(score):
        raise ValueError(f"The {family.name} family scored {score} on {split} proteins.")
    return float(score)


def _predict(projected: Tensor, weights: Tensor, offset: Tensor) -> np.ndarray:
    # projected: (n_split, k); weights: (k, t); offset: (t,)
    return (projected @ weights + offset).cpu().numpy()  # (n_split, t)


def spectral(train: Tensor) -> tuple[Tensor, Tensor]:
    """Squared singular values and right singular vectors of standardized training features, from the smaller Gram
    matrix; directions with no variance are dropped."""
    # train: (n, w)
    if train.shape[1] <= train.shape[0]:
        values, vectors = torch.linalg.eigh(train.T @ train)  # (w,), (w, w)
    else:
        values, left = torch.linalg.eigh(train @ train.T)  # (n,), (n, n)
        vectors = train.T @ left / values.clamp(min=torch.finfo(values.dtype).tiny).sqrt()  # (w, n)
    keep = values > values.max() * 1e-12  # (w,) or (n,)
    return values[keep], vectors[:, keep]  # (k,), (w, k)


def readout_scores(features: Mapping[str, np.ndarray], families: Sequence[Family], *, ranks: Sequence[int] = RANKS,
                   penalties: Sequence[float] = PENALTIES, share: float = SHARE, device: str = "cpu") -> pd.DataFrame:
    """Every family that reads one set of features, full and cut to each rank below its target count."""
    # features: (n_split, w) by split
    raw = {split: torch.as_tensor(np.asarray(array, dtype=np.float64), device=device) for split, array in features.items()}
    mean, scale = raw["train"].mean(dim=0), raw["train"].std(dim=0).clamp(min=1e-12)  # (w,), (w,)
    standard = {split: (array - mean) / scale for split, array in raw.items()}  # (n_split, w)
    values, vectors = spectral(standard["train"])  # (k,), (w, k)
    projected = {split: standard[split] @ vectors for split in ("validation", "test")}  # (n_split, k)
    rows = []
    for family in families:
        targets = torch.as_tensor(family.values["train"], dtype=torch.float64, device=device)  # (n_train, t)
        offset = targets.mean(dim=0)  # (t,)
        moment = vectors.T @ (standard["train"].T @ (targets - offset))  # (k, t)
        searched = [(family_score(_predict(projected["validation"], moment / (values + penalty)[:, None], offset), family,
                                  "validation"), penalty) for penalty in penalties]
        _, penalty = max(searched)
        weights = moment / (values + penalty)[:, None]  # (k, t)
        _, directions = torch.linalg.eigh(weights.T @ ((values + penalty)[:, None] * weights))  # (t, t), ascending
        directions = directions.flip(dims=(1,))  # (t, t), descending
        chance = CHANCE[family.metric]
        cut = [rank for rank in ranks if rank < family.targets] + [family.targets]
        scores = {}
        for rank in cut:
            kept = weights @ directions[:, :rank] @ directions[:, :rank].T  # (k, t)
            scores[rank] = {split: family_score(_predict(projected[split], kept, offset), family, split)
                            for split in ("validation", "test")}
        full = scores[family.targets]["validation"] - chance
        dimension = next(rank for rank in cut if scores[rank]["validation"] - chance >= share * full)
        centered = projected["validation"] @ weights  # (n_validation, t)
        singular = torch.linalg.svdvals(centered - centered.mean(dim=0))  # (min(n, t),)
        stable_rank = float((singular ** 2).sum() / singular[0] ** 2)
        rows.extend({"family": family.name, "metric": family.metric, "targets": family.targets, "rank": rank,
                     "full": rank == family.targets, "validation": score["validation"], "test": score["test"],
                     "penalty": penalty, "dimension": dimension, "stable_rank": stable_rank} for rank, score in scores.items())
    return pd.DataFrame(rows)


def cofiring_blocks(correlation: np.ndarray, *, threshold: float = BLOCK_CORRELATION) -> np.ndarray:
    """Each pole's block: average-linkage clusters of one minus the poles' correlation, cut where merged poles
    correlate below `threshold` on average."""
    # correlation: (p, p)
    symmetric = (correlation.astype(np.float64) + correlation.T.astype(np.float64)) / 2  # (p, p)
    distance = 1.0 - symmetric  # (p, p)
    np.fill_diagonal(distance, 0.0)
    tree = hierarchy.linkage(squareform(distance, checks=False), method="average")  # (p - 1, 4)
    return hierarchy.fcluster(tree, t=1.0 - threshold, criterion="distance") - 1  # (p,)


def _block_weights(train: Tensor, columns: Tensor, targets: Tensor, penalty: float) -> Tensor:
    """Ridge weights of equal-size column sets on train-centered targets, one solve per set."""
    # train: (n, p); columns: (b, s); targets: (n, t), centered
    gathered = train[:, columns].permute(1, 0, 2)  # (b, n, s)
    identity = torch.eye(columns.shape[1], dtype=train.dtype, device=train.device)  # (s, s)
    gram = gathered.transpose(1, 2) @ gathered + penalty * identity  # (b, s, s)
    return torch.linalg.solve(gram, gathered.transpose(1, 2) @ targets)  # (b, s, t)


def block_validation_r2(standard: Mapping[str, Tensor], columns: Tensor, targets: Mapping[str, Tensor], *,
                        penalty: float = BLOCK_PENALTY) -> Tensor:
    """Validation R squared, averaged over targets, of a ridge readout on each of equal-size column sets."""
    # standard: (n_split, p) by split; columns: (b, s); targets: (n_split, t) by split
    offset = targets["train"].mean(dim=0)  # (t,)
    truth = targets["validation"]  # (n_validation, t)
    total = ((truth - truth.mean(dim=0)) ** 2).sum(dim=0)  # (t,)
    chunk = max(1, CHUNK_ELEMENTS // (standard["train"].shape[0] * columns.shape[1]))
    scores = []
    for start in range(0, columns.shape[0], chunk):
        part = columns[start:start + chunk]  # (c, s)
        weights = _block_weights(standard["train"], part, targets["train"] - offset, penalty)  # (c, s, t)
        predicted = standard["validation"][:, part].permute(1, 0, 2) @ weights + offset  # (c, n_validation, t)
        residual = ((truth - predicted) ** 2).sum(dim=1)  # (c, t)
        scores.append((1 - residual / total).mean(dim=1))  # (c,)
    return torch.cat(scores)  # (b,)


def best_block(standard: Mapping[str, Tensor], groups: Sequence[Tensor], family: Family, targets: Mapping[str, Tensor], *,
               penalty: float = BLOCK_PENALTY) -> tuple[float, float, int]:
    """The column set with the best validation R squared among `groups` (equal-size sets each), its test score by the
    family's metric, and its size."""
    # standard: (n_split, p) by split; groups: (b_s, s) each; targets: (n_split, t) by split
    best = (-np.inf, None)
    for columns in groups:
        scores = block_validation_r2(standard, columns, targets, penalty=penalty)  # (b_s,)
        index = int(scores.argmax())
        if float(scores[index]) > best[0]:
            best = (float(scores[index]), columns[index])
    validation, chosen = best
    offset = targets["train"].mean(dim=0)  # (t,)
    weights = _block_weights(standard["train"], chosen[None, :], targets["train"] - offset, penalty)[0]  # (s, t)
    predicted = (standard["test"][:, chosen] @ weights + offset).cpu().numpy()  # (n_test, t)
    return validation, family_score(predicted, family, "test"), int(chosen.numel())


def run_blocks(features: Mapping[str, np.ndarray], families: Sequence[Family], blocks: np.ndarray, *,
               sizes: tuple[int, int] = BLOCK_SIZES, draws: int = NULL_DRAWS, seed: int = SEED,
               device: str = "cpu") -> pd.DataFrame:
    """E10's co-firing blocks for families that share `features`' rows: the best block against `draws` redraws of every
    tested block as random poles of its size."""
    # features: (n_split, p) by split; blocks: (p,) block of each pole
    raw = {split: torch.as_tensor(np.asarray(array, dtype=np.float64), device=device) for split, array in features.items()}
    mean, scale = raw["train"].mean(dim=0), raw["train"].std(dim=0).clamp(min=1e-12)  # (p,), (p,)
    standard = {split: (array - mean) / scale for split, array in raw.items()}  # (n_split, p)
    members = [np.flatnonzero(blocks == block) for block in np.unique(blocks)]
    tested = [columns for columns in members if sizes[0] <= len(columns) <= sizes[1]]
    if not tested:
        raise ValueError(f"No co-firing block has between {sizes[0]} and {sizes[1]} poles.")
    counts = pd.Series([len(columns) for columns in tested]).value_counts().sort_index()
    groups = [torch.as_tensor(np.stack([columns for columns in tested if len(columns) == size]), device=device)
              for size in counts.index]  # (b_s, s) each
    poles = len(blocks)
    rng = np.random.default_rng(seed)
    nulls = [[torch.as_tensor(np.stack([rng.choice(poles, size=size, replace=False) for _ in range(count)]), device=device)
              for size, count in counts.items()] for _ in range(draws)]  # (b_s, s) each
    rows = []
    for family in families:
        if family.metric == "spearman":
            raise ValueError(f"Co-firing blocks read concept families with held-out targets, not {family.name}.")
        targets = {split: torch.as_tensor(np.asarray(values, dtype=np.float64), device=device)
                   for split, values in family.values.items()}  # (n_split, t)
        validation, test, size = best_block(standard, groups, family, targets)
        null = np.array([best_block(standard, draw, family, targets)[1] for draw in nulls])  # (draws,)
        rows.append({"family": family.name, "metric": family.metric, "blocks": len(tested), "poles_in_blocks":
                     int(sum(len(columns) for columns in tested)), "best_size": size, "best_validation_r2": validation,
                     "best_test": test, "null_mean": float(null.mean()), "null_low": float(np.percentile(null, 2.5)),
                     "null_high": float(np.percentile(null, 97.5)), "null_at_or_above": float((null >= test).mean())})
    return pd.DataFrame(rows)


def run_e10_blocks(extraction: Path, families: Sequence[Family], block: int, correlation: np.ndarray, *,
                   device: str = "cpu", log: Callable[[str], None] = print) -> pd.DataFrame:
    """E10's co-firing blocks at one block of a concept extraction, beside each family's readout on every pole."""
    # correlation: (p, p), the native poles' correlation over E8's residues
    blocks = cofiring_blocks(correlation)  # (p,)
    poles = read_feature(extraction, block, "poles_mean")  # (n, p)
    if poles.shape[1] != len(blocks):
        raise ValueError(f"The co-firing matrix covers {len(blocks)} poles, the extraction {poles.shape[1]}.")
    groups: dict[str, list[Family]] = {}
    for family in families:
        groups.setdefault(family.task, []).append(family)
    tables = []
    for members in groups.values():
        split_features = {split: poles[members[0].rows[split]] for split in SPLITS}  # (n_split, p)
        every = readout_scores(split_features, members, device=device)
        every = every[every["full"]].set_index("family")["test"].rename("all_poles_test")
        tables.append(run_blocks(split_features, members, blocks, device=device).join(every, on="family"))
    table = pd.concat(tables, ignore_index=True).assign(block=block)
    log(f"E10 co-firing blocks at block {block}: {int(table['blocks'].iloc[0])} blocks of "
        f"{BLOCK_SIZES[0]} to {BLOCK_SIZES[1]} poles")
    return table


def run_e10(
    extractions: Mapping[str, Path],
    families: Sequence[Family],
    depths: Sequence[int],
    *,
    features: Sequence[str] = FEATURES,
    device: str = "cpu",
    log: Callable[[str], None] = print,
) -> pd.DataFrame:
    """Every family at every depth block and pooled feature, each family read from its source's extraction."""
    tables = []
    for block in depths:
        for feature in features:
            groups: dict[tuple[str, str], list[Family]] = {}
            for family in families:
                groups.setdefault((family.source, family.task), []).append(family)
            for (source, _), members in groups.items():
                array = read_feature(extractions[source], block, feature)  # (n, w)
                split_features = {split: array[members[0].rows[split]] for split in SPLITS}  # (n_split, w)
                tables.append(readout_scores(split_features, members, device=device).assign(block=block, features=feature))
            log(f"E10 block {block}, {feature}: {len(families)} families read")
    return pd.concat(tables, ignore_index=True)
