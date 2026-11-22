"""The compendium's tables: their Arrow schemas, and a writer that streams rows into one Parquet file.

Read from the sources, per UniProtKB accession:
    entries            one row per entry: its sequence and the metadata the shortcut registry reads
    assertions         one row per (term, evidence code, position) an accession is asserted for, positive or NOT
    measurement_texts  the biophysicochemical statements of an entry, raw, with their evidence, for the measurement readers
Pooled, per distinct sequence (`protein_id`, the SHA-256 of the sequence):
    proteins           one row per sequence, its accessions merged
    assertions         the rows above keyed by protein, with their tier and fundamental aspect
    hierarchy          one row per typed edge between two concepts
    concepts           one row per concept the ontologies name: its name, definition and kind
    clusters           one row per protein: its cluster at each level of the cascade
    vocabulary         one row per term, with its support per tier and split and its audit
"""

from __future__ import annotations

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from collections.abc import Iterator, Mapping
from pathlib import Path
from types import TracebackType


WRITE_BATCH = 200_000

ENTRY_SCHEMA = pa.schema([
    ("accession", pa.string()),
    ("secondary_accessions", pa.list_(pa.string())),
    ("entry_name", pa.string()),
    ("dataset", pa.string()),
    ("sequence", pa.string()),
    ("fragment", pa.bool_()),
    ("created", pa.string()),
    ("modified", pa.string()),
    ("entry_version", pa.int32()),
    ("sequence_version", pa.int32()),
    # 1 (evidence at protein level) to 5 (uncertain), UniProt's protein existence.
    ("protein_existence", pa.int8()),
    ("taxon_id", pa.int64()),
    ("organism", pa.string()),
    ("lineage", pa.list_(pa.string())),
    ("proteomes", pa.list_(pa.string())),
    ("protein_name", pa.string()),
    # The entry's references (its citation count) and its PDB cross-references.
    ("references", pa.int32()),
    ("structures", pa.int32()),
])

ASSERTION_SCHEMA = pa.schema([
    ("accession", pa.string()),
    ("aspect", pa.string()),
    ("source_database", pa.string()),
    ("term", pa.string()),
    ("label", pa.string()),
    # A NOT assertion: the source states the protein lacks the term.
    ("negated", pa.bool_()),
    # The ECO or GAF evidence code, `match:<member database>` for an InterPro match, "" when the source gives none.
    ("code", pa.string()),
    ("source", pa.string()),
    ("assigned_by", pa.string()),
    # Citations, `PubMed:<id>` and the like, joined by "|".
    ("reference", pa.string()),
    # GO's relation (`enables`, `located_in`, ...), "" elsewhere.
    ("relation", pa.string()),
    # Residue positions, 1-based and inclusive, for a local term; null for a protein-level one.
    ("start", pa.int32()),
    ("end", pa.int32()),
    # What the source wrote beside the term: a feature's description, GO's with/from.
    ("note", pa.string()),
])

MEASUREMENT_TEXT_SCHEMA = pa.schema([
    ("accession", pa.string()),
    # kinetics_km, kinetics_vmax, kinetics_text, ph_dependence, temperature_dependence, redox_potential, absorption_max.
    ("kind", pa.string()),
    ("text", pa.string()),
    # Each distinct evidence code of the statement, sorted, and in the same place the citations of that code joined by "|" ("" for
    # none), so a reader can ask which papers stand behind its experimental code.
    ("codes", pa.list_(pa.string())),
    ("references", pa.list_(pa.string())),
])

PROTEIN_SCHEMA = pa.schema([
    ("protein_id", pa.string()),
    ("sequence", pa.string()),
    ("length", pa.int32()),
    ("accessions", pa.list_(pa.string())),
    # The first Swiss-Prot accession of the sequence, else its first TrEMBL one.
    ("primary_accession", pa.string()),
    ("reviewed", pa.bool_()),
    # The pool subsets that admitted the sequence (swissprot, trembl_goa_experimental, trembl_score_5, trembl_score_4, trembl_pe1).
    ("admitted_by", pa.list_(pa.string())),
    ("protein_existence", pa.int8()),
    ("annotation_score", pa.int8()),
    ("taxon_id", pa.int64()),
    ("taxa", pa.list_(pa.int64())),
    ("organism", pa.string()),
    ("domain", pa.string()),
    ("kingdom", pa.string()),
    ("phylum", pa.string()),
    ("class", pa.string()),
    ("order", pa.string()),
    ("family", pa.string()),
    ("genus", pa.string()),
    ("species", pa.string()),
    ("proteomes", pa.list_(pa.string())),
    ("reference_proteome", pa.bool_()),
    ("structures", pa.int32()),
    ("references", pa.int32()),
    ("created", pa.string()),
    ("modified", pa.string()),
    ("protein_name", pa.string()),
])

POOLED_ASSERTION_SCHEMA = pa.schema([
    ("protein_id", pa.string()),
    ("term_id", pa.string()),
    ("fundamental_aspect", pa.string()),
    # experimental, signature, curated or guard (`tiers.assertion_tier`).
    ("tier", pa.string()),
    *ASSERTION_SCHEMA,
])

# Edges join concepts, a term's (source database, accession) without its aspect, so one edge serves every aspect that names the
# concept: InterPro's tree carries both `interpro` and `local_interpro`, ChEBI's both `cofactor` and `local_binding`.
HIERARCHY_SCHEMA = pa.schema([
    ("child_database", pa.string()),
    ("child", pa.string()),
    ("parent_database", pa.string()),
    ("parent", pa.string()),
    # is_a, part_of (GO, locations, pathways), ec_parent, lineage (taxonomy), clan_member (Pfam), maps_to (a PTM's PSI-MOD term).
    ("relation", pa.string()),
])

CONCEPT_SCHEMA = pa.schema([
    ("source_database", pa.string()),
    ("accession", pa.string()),
    ("name", pa.string()),
    ("definition", pa.string()),
    # What the source calls the concept: a GO namespace, an InterPro entry type, a taxonomic rank, a keyword category.
    ("kind", pa.string()),
])


class RowWriter:
    """Streams rows into one Parquet file in row groups, and moves the file into place only when it closes cleanly.

    Each row is a mapping from column name to value; a column a row leaves out is null. A writer that fails removes its partial
    file, so a path holds a whole table or nothing.
    """

    def __init__(self, path: Path, schema: pa.Schema, *, batch: int = WRITE_BATCH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.schema = schema
        self.batch = batch
        self._temporary = path.with_name(path.name + ".part")
        self._writer = pq.ParquetWriter(self._temporary, schema, compression="zstd")
        self._columns: dict[str, list[object]] = {name: [] for name in schema.names}
        self._pending = 0
        self.count = 0

    def add(self, row: Mapping[str, object]) -> None:
        unknown = set(row) - set(self._columns)
        if unknown:
            raise KeyError(f"{self.path.name} has no columns {sorted(unknown)}")
        for name, values in self._columns.items():
            values.append(row.get(name))
        self._pending += 1
        if self._pending >= self.batch:
            self._flush()

    def add_table(self, table: pa.Table) -> None:
        """Write `table`, whose columns are this file's, after the rows added before it."""
        self._flush()
        if table.num_rows:
            self._writer.write_table(table.select(self.schema.names).cast(self.schema))
            self.count += table.num_rows

    def _flush(self) -> None:
        if not self._pending:
            return
        self._writer.write_table(pa.table(self._columns, schema=self.schema))
        self.count += self._pending
        self._columns = {name: [] for name in self.schema.names}
        self._pending = 0

    def close(self) -> int:
        """Finish the file, move it into place, and return its row count."""
        self._flush()
        self._writer.close()
        self._temporary.replace(self.path)
        return self.count

    def abort(self) -> None:
        """Drop the partial file; the path keeps what it held before."""
        self._writer.close()
        self._temporary.unlink(missing_ok=True)

    def __enter__(self) -> RowWriter:
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None, traceback: TracebackType | None) -> None:
        if kind is None:
            self.close()
        else:
            self.abort()


def write_table(path: Path, table: pa.Table) -> int:
    """Write one whole table, zstd Parquet, moved into place once written, and return its row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    pq.write_table(table, temporary, compression="zstd")
    temporary.replace(path)
    return table.num_rows


def take_by_key(keys: pa.ChunkedArray | pa.Array, table: pa.Table, key: str, column: str) -> pa.ChunkedArray:
    """`table[column]` at the row whose `key` equals each of `keys`, null where `table` has none; `table` holds each key once.

    A left join would do the same, but Arrow's hash join cannot carry a list column, and this can."""
    return pc.take(table[column], pc.index_in(keys, value_set=table[key].combine_chunks()))


def split_frame(protein_to_split: Mapping[str, str]) -> pa.Table:
    """(protein_id, split): a split assignment as a table, to join on."""
    return pa.table({"protein_id": list(protein_to_split), "split": list(protein_to_split.values())},
                    schema=pa.schema([("protein_id", pa.string()), ("split", pa.string())]))


# The first hex digit of a protein id (a SHA-256), by which the pool's assertions are written and read a partition at a time. In
# digit order the partitions are protein-id order, so a file written partition after partition, each sorted, is sorted whole, and
# no stage holds the full pool's rows (about 150 million, 2026-10-20) at once.
PARTITIONS = "0123456789abcdef"


def partition_filter(digit: str) -> pc.Expression:
    """The rows of one partition, protein ids from `digit` up to the next digit: a filter for a table, or for a Parquet read, which
    a file sorted by protein id answers from its row groups' statistics without reading the other partitions."""
    index = PARTITIONS.index(digit)
    rows = pc.field("protein_id") >= digit
    if index + 1 < len(PARTITIONS):
        rows = rows & (pc.field("protein_id") < PARTITIONS[index + 1])
    return rows


def read_partition(path: Path, digit: str, columns: list[str] | None = None, rows: pc.Expression | None = None) -> pa.Table:
    """One partition's rows of a Parquet file keyed by protein id, with `columns`, and only those `rows` selects when given."""
    return pq.read_table(path, columns=columns, filters=partition_filter(digit) if rows is None else partition_filter(digit) & rows)


class PartitionWriter:
    """Rows spilled into one Parquet file a partition under `directory`, by the first digit of their protein id.

    A row whose protein id begins with no hex digit belongs to no partition and is refused rather than dropped.
    """

    def __init__(self, directory: Path, schema: pa.Schema) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.schema = schema
        self.paths = {digit: directory / f"{digit}.parquet" for digit in PARTITIONS}
        self._writers = {digit: pq.ParquetWriter(path, schema, compression="zstd") for digit, path in self.paths.items()}

    def add(self, table: pa.Table) -> None:
        digits = pc.utf8_slice_codeunits(table["protein_id"], 0, 1)
        placed = 0
        for digit, writer in self._writers.items():
            part = table.filter(pc.equal(digits, digit))
            if part.num_rows:
                writer.write_table(part.select(self.schema.names).cast(self.schema))
                placed += part.num_rows
        if placed != table.num_rows:
            raise ValueError(f"{table.num_rows - placed} rows have a protein id that begins with no hex digit")

    def close(self) -> dict[str, Path]:
        """Finish every partition's file and return their paths, by digit."""
        for writer in self._writers.values():
            writer.close()
        return self.paths


def iter_rows(path: Path, columns: list[str] | None = None, *, batch: int = WRITE_BATCH) -> Iterator[dict[str, object]]:
    """Each row of a Parquet file as a mapping, in file order, holding one batch in memory at a time."""
    for chunk in pq.ParquetFile(path).iter_batches(batch_size=batch, columns=columns):
        rows = chunk.to_pydict()
        names = list(rows)
        for index in range(chunk.num_rows):
            yield {name: rows[name][index] for name in names}
