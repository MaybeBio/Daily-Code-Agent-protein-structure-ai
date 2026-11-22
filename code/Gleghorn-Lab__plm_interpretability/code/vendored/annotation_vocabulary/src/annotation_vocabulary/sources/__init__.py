"""Acquisition and parsing adapters for external annotation sources."""

from .acquisition import (
    AcquiredSource,
    FetchSpec,
    SourceSpec,
    acquire_source,
    acquire_sources,
    fetch_source,
    sha256_file,
)
from .interpro import (
    InterProCoordinateMatch,
    InterProParserAudit,
    join_interpro_coordinates,
    parse_interpro_coordinates,
)
from .taxonomy import (
    DeletedTaxonError,
    TaxonRecord,
    Taxonomy,
    TaxonomyCycleError,
    TaxonomyError,
    UnresolvedTaxonError,
)
from .uniprot import SwissProtParserAudit, parse_swissprot


__all__ = [
    "AcquiredSource",
    "DeletedTaxonError",
    "FetchSpec",
    "InterProCoordinateMatch",
    "InterProParserAudit",
    "SourceSpec",
    "SwissProtParserAudit",
    "TaxonRecord",
    "Taxonomy",
    "TaxonomyCycleError",
    "TaxonomyError",
    "UnresolvedTaxonError",
    "acquire_source",
    "acquire_sources",
    "fetch_source",
    "join_interpro_coordinates",
    "parse_interpro_coordinates",
    "parse_swissprot",
    "sha256_file",
]
