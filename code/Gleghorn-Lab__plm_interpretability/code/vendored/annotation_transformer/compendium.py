"""The annotation compendium as the annotation transformer reads it: entries without organism terms, at most 64 tokens.

`Synthyra/annotation_compendium_v1`'s default config holds one row a distinct sequence, with its vocabulary tokens in
ascending order (the vocabulary's grammar) and the ids `tables/tokens.parquet` gives them. An entry is a row's tokens
without those of the organism aspect: taxa and traits a protein inherits from its species, which the release scores on
its organism split and this model does not read. A held-out row's curated terms are already masked by the release, and
the reader refuses a validation or test row that holds one. A row left with no term is dropped. The token space appends
the specials after the terms in the grammar's order, `<pad>`, `<bos>`, `<eos>`, `<mask>`, `<unk>`, so a term keeps the
release's id.

A model input is `<bos>`, at most 62 terms in ascending order, and `<eos>`: 64 tokens. In training, an entry of more than
62 terms is cut to a uniformly random 62. A shorter entry is thinned with probability one half to a uniformly random k of
its n terms, with k drawn uniformly from 1 to n, so the model learns to read incomplete entries. Every cut keeps ascending
order. A held-out entry is never thinned, and is cut once by a generator seeded from its protein id. Training batches draw
0.9-identity clusters uniformly, without replacement within a batch, and one random member of each, so a large family
does not fill a batch.

Symbols: n terms of an entry; k terms kept.
"""

from __future__ import annotations

import random
import pyarrow.parquet as pq

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path


SPECIALS = ("<pad>", "<bos>", "<eos>", "<mask>", "<unk>")
MAX_TOKENS = 64  # with <bos> and <eos>
MAX_TERMS = MAX_TOKENS - 2
THIN_PROBABILITY = 0.5
ORGANISM_ASPECT = "organism"
CURATED_TIER = "curated"
HELD_OUT_SPLITS = ("validation", "test")
TOKENS_TABLE = Path("tables") / "tokens.parquet"
VOCABULARY_TABLE = Path("tables") / "vocabulary.parquet"
CLUSTERS_TABLE = Path("tables") / "clusters.parquet"
TRAINING_CLUSTER = "c090"  # the release's `cluster_id`, which batches draw over
BOOTSTRAP_CLUSTER = "c050"  # the split's enforced level, which intervals resample


@dataclass(frozen=True, slots=True)
class CompendiumSplit:
    """The rows of one split that keep a term: protein, entry and the two cluster levels, with how many rows fell."""

    protein_id: list[str]
    entries: list[list[int]]  # ascending term ids, no organism term, at least one each
    c090: list[str]
    c050: list[str]
    dropped: int  # rows whose every term was an organism term


def is_compendium(release: Path) -> bool:
    """Whether a release directory is a compendium release, whose token table sits under `tables/`."""
    return (release / TOKENS_TABLE).is_file()


def term_count(release: Path) -> int:
    """The number of vocabulary terms, whose ids must be 0 to n - 1; the specials follow them."""
    tokens = pq.read_table(release / TOKENS_TABLE, columns=["token"]).column("token").to_pylist()
    if sorted(tokens) != list(range(len(tokens))):
        raise ValueError(f"{release / TOKENS_TABLE} must number its terms 0 to n - 1.")
    return len(tokens)


def organism_tokens(release: Path) -> frozenset[int]:
    """The ids of the terms whose fundamental aspect is the organism, from the release's vocabulary."""
    tokens = pq.read_table(release / TOKENS_TABLE, columns=["term_id", "token"]).to_pydict()
    vocabulary = pq.read_table(release / VOCABULARY_TABLE, columns=["term_id", "fundamental_aspect"]).to_pydict()
    aspect_of = dict(zip(vocabulary["term_id"], vocabulary["fundamental_aspect"], strict=True))
    missing = [term for term in tokens["term_id"] if term not in aspect_of]
    if missing:
        raise ValueError(f"{len(missing)} token terms are not in the vocabulary table, such as {missing[:3]}.")
    return frozenset(token for term, token in zip(tokens["term_id"], tokens["token"], strict=True)
                     if aspect_of[term] == ORGANISM_ASPECT)


def read_split(release: Path, split: str) -> CompendiumSplit:
    """One split's entries without organism terms, with each row's 0.9 and 0.5 identity clusters."""
    organism = organism_tokens(release)
    table = pq.read_table(release / f"{split}.parquet", columns=["protein_id", "cluster_id", "tokens", "tiers"]).to_pydict()
    clusters = pq.read_table(release / CLUSTERS_TABLE, columns=["protein_id", BOOTSTRAP_CLUSTER]).to_pydict()
    bootstrap_of = dict(zip(clusters["protein_id"], clusters[BOOTSTRAP_CLUSTER], strict=True))
    proteins, entries, fine, coarse = [], [], [], []
    rows = zip(table["protein_id"], table["cluster_id"], table["tokens"], table["tiers"], strict=True)
    for protein, cluster, tokens, tiers in rows:
        if split in HELD_OUT_SPLITS and CURATED_TIER in tiers:
            raise ValueError(f"{split} row {protein} holds a curated term, which the release masks in held-out splits.")
        if any(later <= earlier for earlier, later in zip(tokens, tokens[1:], strict=False)):
            raise ValueError(f"{split} row {protein} is not in the vocabulary's ascending order.")
        entry = [token for token in tokens if token not in organism]
        if entry:
            proteins.append(protein)
            entries.append(entry)
            fine.append(cluster)
            coarse.append(bootstrap_of[protein])
    return CompendiumSplit(proteins, entries, fine, coarse, dropped=len(table["protein_id"]) - len(proteins))


def train_entry(terms: Sequence[int], generator: random.Random, thin_probability: float = THIN_PROBABILITY) -> list[int]:
    """One training presentation of an ascending entry: cut to a random 62 terms when longer, else thinned or whole."""
    if len(terms) > MAX_TERMS:
        return sorted(generator.sample(terms, MAX_TERMS))
    if generator.random() < thin_probability:
        return sorted(generator.sample(terms, generator.randint(1, len(terms))))
    return list(terms)


def held_out_entry(terms: Sequence[int], protein_id: str) -> list[int]:
    """A held-out entry as every evaluation reads it: whole, or cut to 62 terms by a generator seeded from the protein id."""
    if len(terms) <= MAX_TERMS:
        return list(terms)
    return sorted(random.Random(int(protein_id[:16], 16)).sample(list(terms), MAX_TERMS))


def wrap(terms: Sequence[int], bos: int, eos: int) -> list[int]:
    """The model input of an entry of at most 62 terms: `<bos>`, the terms, `<eos>`."""
    if len(terms) > MAX_TERMS:
        raise ValueError(f"An entry of {len(terms)} terms exceeds the {MAX_TERMS} a 64-token input holds.")
    return [bos, *terms, eos]


def cluster_batches(clusters: Sequence[str], size: int, generator: random.Random) -> Iterator[list[int]]:
    """Endless batches of row indices: `size` distinct clusters drawn uniformly, and one random member of each."""
    groups: dict[str, list[int]] = {}
    for index, cluster in enumerate(clusters):
        groups.setdefault(cluster, []).append(index)
    members = list(groups.values())
    if size > len(members):
        raise ValueError(f"A batch of {size} distinct clusters needs at least that many; the split has {len(members)}.")
    while True:
        yield [generator.choice(members[cluster]) for cluster in generator.sample(range(len(members)), size)]
