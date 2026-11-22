"""Assertions: one term of one accession, with the source and the evidence code that admit it."""

from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from ..schema import TermKey


GO_ASPECT_LETTERS = {"P": "go_bp", "F": "go_mf", "C": "go_cc"}
OBO_NAMESPACE_ASPECTS = {
    "biological_process": "go_bp", "molecular_function": "go_mf", "cellular_component": "go_cc",
}
# The aspects of the release, in the grammar's order. Keywords, Gene3D and every local (residue) aspect are not in it.
RELEASE_ASPECTS = (
    "ec", "go_bp", "go_cc", "go_mf", "interpro", "cofactor", "rhea", "pfam", "disease",
    "subcellular_location", "membrane_topology", "membrane_orientation",
)
SOURCE_GOA = "GOA"
SOURCE_UNIPROT = "UniProtKB"
SOURCE_INTERPRO = "InterPro"
# Assertions of these sources need an experimental evidence code; InterPro matches are computed and admitted as the same tier.
EXPERIMENTAL_SOURCES = (SOURCE_GOA, SOURCE_UNIPROT)
ASSERTION_SCHEMA = pa.schema([
    ("accession", pa.string()),
    ("aspect", pa.string()),
    ("source_database", pa.string()),
    ("term_accession", pa.string()),
    ("label", pa.string()),
    ("source", pa.string()),
    ("code", pa.string()),
])
WRITE_BATCH = 200_000


@dataclass(frozen=True, slots=True)
class Assertion:
    """A protein's term, the source that asserts it and the evidence code it was admitted on."""

    accession: str
    term: TermKey
    label: str
    source: str
    code: str

    @property
    def provenance(self) -> str:
        """`source=code`, the form the release's per-term provenance column uses."""
        return f"{self.source}={self.code}"


class AssertionWriter:
    """Writes assertions to one Parquet file in row groups, so a stage holds only one batch of them in memory."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._temporary = path.with_name(path.name + ".part")
        self._writer = pq.ParquetWriter(self._temporary, ASSERTION_SCHEMA, compression="zstd")
        self._rows: list[Assertion] = []
        self.count = 0

    def add(self, assertion: Assertion) -> None:
        self._rows.append(assertion)
        if len(self._rows) >= WRITE_BATCH:
            self._flush()

    def _flush(self) -> None:
        if not self._rows:
            return
        columns = {
            "accession": [row.accession for row in self._rows],
            "aspect": [row.term.aspect for row in self._rows],
            "source_database": [row.term.source_database for row in self._rows],
            "term_accession": [row.term.accession for row in self._rows],
            "label": [row.label for row in self._rows],
            "source": [row.source for row in self._rows],
            "code": [row.code for row in self._rows],
        }
        self._writer.write_table(pa.table(columns, schema=ASSERTION_SCHEMA))
        self.count += len(self._rows)
        self._rows = []

    def close(self) -> int:
        """Finish the file, move it into place and return how many assertions it holds."""
        self._flush()
        self._writer.close()
        self._temporary.replace(self._path)
        return self.count


def write_assertions(path: Path, assertions: Iterable[Assertion]) -> int:
    """Write assertions to `path`, atomically, and return their count."""
    writer = AssertionWriter(path)
    for assertion in assertions:
        writer.add(assertion)
    return writer.close()


def read_assertions(path: Path) -> Iterator[Assertion]:
    """Every assertion of a file `write_assertions` made, in file order."""
    for batch in pq.ParquetFile(path).iter_batches(batch_size=WRITE_BATCH):
        rows = batch.to_pydict()
        for index in range(batch.num_rows):
            yield Assertion(
                rows["accession"][index],
                TermKey(rows["aspect"][index], rows["source_database"][index], rows["term_accession"][index]),
                rows["label"][index], rows["source"][index], rows["code"][index],
            )


def has_experimental_source(provenance: str) -> bool:
    """Whether a provenance text (`GOA=IDA;InterPro=match:Pfam`) names a source that needs experimental evidence."""
    return any(item.partition("=")[0] in EXPERIMENTAL_SOURCES for item in provenance.split(";"))
