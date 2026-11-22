"""Read NCBI taxonomy dump records without extracting the archive."""

from __future__ import annotations

import io
import tarfile
import zipfile

from dataclasses import dataclass
from pathlib import Path


class TaxonomyError(ValueError):
    """Base class for invalid or incomplete taxonomy data."""


class UnresolvedTaxonError(TaxonomyError):
    """Raised when a taxon or its parent is absent from the dump."""


class DeletedTaxonError(TaxonomyError):
    """Raised when a requested taxon is listed in ``delnodes.dmp``."""


class TaxonomyCycleError(TaxonomyError):
    """Raised when merged IDs or parent IDs form a cycle."""


@dataclass(frozen=True)
class TaxonRecord:
    """A resolved NCBI taxon record."""

    tax_id: int
    scientific_name: str
    rank: str
    parent_tax_id: int


class Taxonomy:
    """Indexed NCBI taxonomy records and stable-ID resolution rules."""

    def __init__(
        self,
        records: dict[int, TaxonRecord],
        merged: dict[int, int],
        deleted: frozenset[int],
    ) -> None:
        self.records = records
        self.merged = merged
        self.deleted = deleted

    @classmethod
    def from_tarball(cls, tarball: Path) -> Taxonomy:
        """Read required dump members directly from a gzip-compressed tarball."""

        with tarfile.open(tarball, mode="r:gz") as archive:
            members = _safe_members(archive)
            contents: dict[str, bytes] = {}
            for name in ("nodes.dmp", "names.dmp", "merged.dmp", "delnodes.dmp"):
                member = members.get(name)
                if member is not None:
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise TaxonomyError(f"cannot read taxonomy member {name}")
                    contents[name] = extracted.read()
        return cls._from_contents(contents)

    @classmethod
    def from_zip(cls, archive: Path) -> Taxonomy:
        """Read the dump members of a dated ``taxdmp_YYYY-MM-DD.zip`` from NCBI's taxdump archive."""

        contents: dict[str, bytes] = {}
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                path = Path(member.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise TaxonomyError(f"unsafe taxonomy archive member: {member.filename}")
                if not member.is_dir() and path.name in {"nodes.dmp", "names.dmp", "merged.dmp", "delnodes.dmp"}:
                    contents[path.name] = bundle.read(member)
        return cls._from_contents(contents)

    @classmethod
    def from_tarball_bytes(cls, payload: bytes) -> Taxonomy:
        """Read a gzip-compressed tarball held in memory."""

        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            members = _safe_members(archive)
            contents: dict[str, bytes] = {}
            for name in ("nodes.dmp", "names.dmp", "merged.dmp", "delnodes.dmp"):
                member = members.get(name)
                if member is not None:
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise TaxonomyError(f"cannot read taxonomy member {name}")
                    contents[name] = extracted.read()
        return cls._from_contents(contents)

    @classmethod
    def _from_contents(cls, contents: dict[str, bytes]) -> Taxonomy:
        required = {"nodes.dmp", "names.dmp"}
        missing = required.difference(contents)
        if missing:
            raise TaxonomyError(f"missing taxonomy members: {sorted(missing)}")
        parents_and_ranks: dict[int, tuple[int, str]] = {}
        for fields in _records(contents["nodes.dmp"]):
            if len(fields) < 3:
                raise TaxonomyError("malformed nodes.dmp record")
            tax_id, parent_id = int(fields[0]), int(fields[1])
            parents_and_ranks[tax_id] = (parent_id, fields[2])

        names: dict[int, str] = {}
        for fields in _records(contents["names.dmp"]):
            if len(fields) >= 4 and fields[3] == "scientific name":
                names[int(fields[0])] = fields[1]
        records = {
            tax_id: TaxonRecord(tax_id, names[tax_id], rank, parent_id)
            for tax_id, (parent_id, rank) in parents_and_ranks.items()
            if tax_id in names
        }
        unnamed = sorted(set(parents_and_ranks).difference(records))
        if unnamed:
            raise TaxonomyError(f"missing scientific names for taxa: {unnamed}")
        merged = {
            int(fields[0]): int(fields[1])
            for fields in _records(contents.get("merged.dmp", b""))
            if len(fields) >= 2
        }
        deleted = frozenset(
            int(fields[0])
            for fields in _records(contents.get("delnodes.dmp", b""))
            if fields
        )
        return cls(records, merged, deleted)

    def resolve_taxon_id(self, tax_id: int) -> int:
        """Resolve a taxon through merged IDs, rejecting deleted IDs and cycles."""

        current = tax_id
        visited: set[int] = set()
        while current in self.merged:
            if current in visited:
                raise TaxonomyCycleError(f"merged taxonomy cycle at taxon {current}")
            visited.add(current)
            current = self.merged[current]
        if current in self.deleted or tax_id in self.deleted:
            raise DeletedTaxonError(f"taxon {tax_id} is deleted")
        if current not in self.records:
            raise UnresolvedTaxonError(f"taxon {tax_id} resolves to unknown taxon {current}")
        return current

    def record(self, tax_id: int) -> TaxonRecord:
        """Return the resolved taxon record."""

        return self.records[self.resolve_taxon_id(tax_id)]

    def lineage(self, tax_id: int) -> tuple[TaxonRecord, ...]:
        """Return root-to-leaf records for a Swiss-Prot taxon ID."""

        current = self.record(tax_id)
        lineage_records: list[TaxonRecord] = []
        visited: set[int] = set()
        while True:
            if current.tax_id in visited:
                raise TaxonomyCycleError(f"parent taxonomy cycle at taxon {current.tax_id}")
            visited.add(current.tax_id)
            lineage_records.append(current)
            if current.parent_tax_id == current.tax_id:
                return tuple(reversed(lineage_records))
            current = self.record(current.parent_tax_id)

    def lineage_ids_and_names(self, tax_id: int) -> tuple[tuple[int, ...], tuple[str, ...]]:
        """Return root-to-leaf taxon IDs and scientific names."""

        lineage = self.lineage(tax_id)
        return tuple(record.tax_id for record in lineage), tuple(
            record.scientific_name for record in lineage
        )


def _safe_members(archive: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    members: dict[str, tarfile.TarInfo] = {}
    for member in archive.getmembers():
        path = Path(member.name)
        if path.is_absolute() or ".." in path.parts or not member.isfile():
            raise TaxonomyError(f"unsafe taxonomy archive member: {member.name}")
        basename = path.name
        if basename in {"nodes.dmp", "names.dmp", "merged.dmp", "delnodes.dmp"}:
            members[basename] = member
    return members


def _records(payload: bytes) -> list[list[str]]:
    records: list[list[str]] = []
    for line in payload.decode("utf-8").splitlines():
        if line.strip():
            fields = [field.strip() for field in line.split("|")]
            if fields and not fields[-1]:
                fields.pop()
            records.append(fields)
    return records
