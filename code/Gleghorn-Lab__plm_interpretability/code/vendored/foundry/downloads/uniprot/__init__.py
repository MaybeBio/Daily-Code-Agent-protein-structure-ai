"""UniProt access: identifier parsing, proteome metadata and FASTA downloads, and ID mapping.

Proteome FASTA files come from UniProt's FTP reference proteomes, one protein per gene, with the
REST stream as the fallback: reviewed entries first, then the whole proteome. ID mapping sends
accessions to UniProt's `idmapping` service in chunks, on parallel sessions, and caches what it
resolves as pickles, so a rerun asks only for accessions it has not mapped.

UniProt answers HTTP 200 to a table it stops streaming partway, ending it with an error line, and
does so every time a table holds an entry it cannot render. So identifiers are mapped by the plain
mapping stream, which renders no entry (`idmapping_pairs`), and entries are read by the accession
lookup, which leaves inactive ones out (`uniprotkb_table`); every table is checked whole before it
is read, and one that stays truncated is split down to the identifiers UniProt cannot render.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import urllib.parse
import pandas as pd
import requests

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any
from Bio import SeqIO
from tqdm.auto import tqdm

from foundry.compression import open_text_maybe_gzip
from foundry.downloads.https import download_file
from foundry.retry import retry, transient
from foundry.serialization import read_json_dict, read_pickle_dict, write_pickle_dict_atomic


UNIPROT_BASE = "https://rest.uniprot.org"
REFERENCE_PROTEOMES_URL = (
    "https://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/reference_proteomes"
)
RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)
LOOKUP_BATCH = 500  # Accessions per UniProtKB accession lookup: its most, and its page size.
INACTIVE_ENTRY_TYPE = "Inactive"  # `entryType` of a deleted, merged or demerged UniProtKB JSON entry.


@dataclass(frozen=True)
class UniProtConfig:
    """The ID mapping databases, the retry count, the timeout and backoff in seconds, and the worker threads.

    An ID-mapping job is polled every `poll_s` seconds and submitted again, up to `job_attempts` times in all, when
    UniProt fails it. A table is fetched up to `stream_attempts` times, each on a new connection, before one that stays
    truncated is split in halves; `pause_s` times the attempt number is waited after each failure.
    """

    idmapping_from: str = "UniProtKB_AC-ID"
    idmapping_to: str = "UniProtKB"
    timeout_s: float = 120.0
    max_retries: int = 8
    backoff_base_s: float = 1.5
    backoff_max_s: float = 60.0
    max_workers: int = 8
    poll_s: float = 2.0
    job_attempts: int = 4
    stream_attempts: int = 2
    pause_s: float = 10.0


@dataclass(frozen=True)
class UniProtTable:
    """A table UniProt returned whole: its header, its data rows, and the identifiers it could not render.

    `unrenderable` holds each identifier whose own job still came back truncated after the table was split down to
    it; its rows are missing from `rows`. `header` is empty when no part of the table came back whole.
    """

    header: tuple[str, ...]
    rows: list[list[str]]
    unrenderable: list[str]


@dataclass
class ProteomeInfo:
    """One UniProt proteome: its identifier, organism, protein count, and taxonomic domain."""

    proteome_id: str
    organism_name: str
    organism_id: int
    protein_count: int
    domain: str = "Eukaryota"

    def __repr__(self) -> str:
        return f"Proteome({self.proteome_id}, {self.organism_name}, {self.protein_count} proteins, {self.domain})"


HUMAN_PROTEOME_ID = "UP000005640"
HUMAN_ORGANISM_ID = 9606

DEFAULT_PROTEOMES = [
    ProteomeInfo(
        proteome_id="UP000000625",
        organism_name="Escherichia coli (strain K12) (K12 / MG1655 / ATCC 47076)",
        organism_id=83333,
        protein_count=0,
        domain="Bacteria",
    ),
    ProteomeInfo(
        proteome_id="UP000002311",
        organism_name="Saccharomyces cerevisiae (strain ATCC 204508 / S288c) (Baker's yeast) (ATCC 204508 / S288c)",
        organism_id=559292,
        protein_count=0,
        domain="Eukaryota",
    ),
    ProteomeInfo(
        proteome_id="UP000000589",
        organism_name="Mus musculus (Mouse) (C57BL/6J)",
        organism_id=10090,
        protein_count=0,
        domain="Eukaryota",
    ),
    ProteomeInfo(
        proteome_id="UP000000803",
        organism_name="Drosophila melanogaster (Fruit fly) (Berkeley)",
        organism_id=7227,
        protein_count=0,
        domain="Eukaryota",
    ),
    ProteomeInfo(
        proteome_id="UP000001570",
        organism_name="Bacillus subtilis (strain 168) (168)",
        organism_id=224308,
        protein_count=0,
        domain="Bacteria",
    ),
    ProteomeInfo(
        proteome_id="UP000005640",
        organism_name="Homo sapiens (Human)",
        organism_id=9606,
        protein_count=0,
        domain="Eukaryota",
    ),
    ProteomeInfo(
        proteome_id="UP000006548",
        organism_name="Arabidopsis thaliana (Mouse-ear cress) (cv. Columbia)",
        organism_id=3702,
        protein_count=0,
        domain="Eukaryota",
    ),
    ProteomeInfo(
        proteome_id="UP000001940",
        organism_name="Caenorhabditis elegans (Bristol N2)",
        organism_id=6239,
        protein_count=0,
        domain="Eukaryota",
    ),
]


def parse_uniprot_id(raw_id: str | None) -> str:
    """The accession in `sp|P08238|HS90B_HUMAN`, or the stripped identifier when it has no `|`; None gives ""."""
    if raw_id is None:
        return ""
    raw = str(raw_id).strip()
    if "|" in raw:
        parts = raw.split("|")
        if len(parts) > 1:
            return parts[1].strip()
    return raw


def parse_id_fields(raw_id: str) -> tuple[str, str]:
    """The accession and upper-case gene symbol in `sp|P08238|HS90B_HUMAN` or `tr|...`.

    Without `|`, the accession is the whole identifier and the gene symbol its first word.
    """
    raw = str(raw_id)
    accession = raw
    gene_symbol = raw

    if "|" in raw:
        parts = raw.split("|")
        if len(parts) > 1:
            accession = parts[1].strip()
        gene_field = parts[-1].strip()
        gene_symbol = gene_field.rsplit("_", 1)[0] if "_" in gene_field else gene_field
    else:
        gene_symbol = raw.split()[0]

    return accession.strip(), gene_symbol.strip().upper()


def fetch_proteome_metadata(proteome_id: str) -> ProteomeInfo:
    """A proteome's metadata from UniProt's REST API, its domain from its taxonomic lineage."""
    metadata = _request_json(f"{UNIPROT_BASE}/proteomes/{proteome_id}.json")

    organism_name = None
    if "organism" in metadata:
        if isinstance(metadata["organism"], dict):
            if "scientificName" in metadata["organism"]:
                organism_name = metadata["organism"]["scientificName"]
            elif "name" in metadata["organism"]:
                organism_name = metadata["organism"]["name"]
        elif isinstance(metadata["organism"], str):
            organism_name = metadata["organism"]
    if organism_name is None and "organism_name" in metadata:
        organism_name = metadata["organism_name"]
    if organism_name is None and "taxonomy" in metadata and isinstance(metadata["taxonomy"], dict):
        taxonomy = metadata["taxonomy"]
        if "scientificName" in taxonomy:
            organism_name = taxonomy["scientificName"]
        elif "name" in taxonomy:
            organism_name = taxonomy["name"]
    assert organism_name is not None, f"Missing organism name for {proteome_id}"

    organism_id = None
    if "organism" in metadata and isinstance(metadata["organism"], dict) and "taxonId" in metadata["organism"]:
        organism_id = int(metadata["organism"]["taxonId"])
    if organism_id is None:
        if "organism_id" in metadata:
            organism_id = int(metadata["organism_id"])
        elif "taxonId" in metadata:
            organism_id = int(metadata["taxonId"])
        elif "taxonomyId" in metadata:
            organism_id = int(metadata["taxonomyId"])
        elif "taxonomy" in metadata and isinstance(metadata["taxonomy"], dict) and "taxonId" in metadata["taxonomy"]:
            organism_id = int(metadata["taxonomy"]["taxonId"])
    assert organism_id is not None, f"Missing organism id for {proteome_id}"

    protein_count = 0
    if "protein_count" in metadata:
        protein_count = int(metadata["protein_count"])
    elif "proteinCount" in metadata:
        protein_count = int(metadata["proteinCount"])

    lineage = _extract_lineage_from_metadata(metadata)
    if lineage == "":
        lineage = _fetch_taxonomy_lineage(organism_id)
    assert lineage != "", f"Missing lineage for {proteome_id}; provide a metadata JSON mapping."

    return ProteomeInfo(
        proteome_id=proteome_id,
        organism_name=organism_name,
        organism_id=organism_id,
        protein_count=protein_count,
        domain=_extract_domain_from_lineage(lineage),
    )


def load_proteome_metadata_json(path: str) -> dict[str, ProteomeInfo]:
    """Proteome metadata from a JSON file mapping each proteome identifier to its fields.

    Each entry needs `organism_id` and `organism_name`, and `domain` or a `lineage` to take it
    from; without either, the lineage is fetched from UniProt's taxonomy endpoint.
    """
    entries = read_json_dict(path)
    assert isinstance(entries, dict), "Proteome metadata JSON must be a dict"

    proteomes: dict[str, ProteomeInfo] = {}
    for proteome_id, entry in entries.items():
        assert isinstance(entry, dict), f"Metadata for {proteome_id} must be a dict"
        assert "organism_id" in entry, f"Missing organism_id for {proteome_id}"
        assert "organism_name" in entry, f"Missing organism_name for {proteome_id}"

        organism_id = int(entry["organism_id"])
        if "domain" in entry:
            domain = entry["domain"]
        else:
            lineage = _normalize_lineage(entry["lineage"]) if "lineage" in entry else ""
            if lineage == "":
                lineage = _fetch_taxonomy_lineage(organism_id)
            assert lineage != "", f"Missing lineage for {proteome_id}; add lineage or domain to JSON."
            domain = _extract_domain_from_lineage(lineage)

        proteomes[proteome_id] = ProteomeInfo(
            proteome_id=proteome_id,
            organism_name=entry["organism_name"],
            organism_id=organism_id,
            protein_count=int(entry["protein_count"]) if "protein_count" in entry else 0,
            domain=domain,
        )
    return proteomes


def parse_proteome_tsv(tsv_path: str) -> list[ProteomeInfo]:
    """Proteomes from UniProt's proteome table export, with each domain taken from its lineage."""
    proteome_table = pd.read_csv(tsv_path, sep="\t")

    proteomes: list[ProteomeInfo] = []
    for _, row in proteome_table.iterrows():
        lineage = row.get("Taxonomic lineage", "")
        proteomes.append(
            ProteomeInfo(
                proteome_id=row["Proteome Id"],
                organism_name=row["Organism"],
                organism_id=int(row["Organism Id"]),
                protein_count=int(row["Protein count"]),
                domain=_extract_domain_from_lineage(str(lineage)),
            )
        )
    return proteomes


def download_proteome_fasta(
    proteome_id: str,
    organism_id: int,
    domain: str,
    output_path: str,
    max_retries: int = 3,
    retry_delay: float = 5.0,
) -> bool:
    """Download a reference proteome's FASTA, one canonical protein per gene, from UniProt's FTP.

    The file is `<domain>/<proteome_id>/<proteome_id>_<organism_id>.fasta.gz`. Each failed attempt,
    an empty file included, is retried after a delay that doubles; the result says whether one
    succeeded.
    """
    url = f"{REFERENCE_PROTEOMES_URL}/{domain}/{proteome_id}/{proteome_id}_{organism_id}.fasta.gz"
    return _download_fasta(
        url,
        None,
        output_path,
        f"{proteome_id} from {domain}",
        "sequences (one per gene)",
        max_retries,
        retry_delay,
        url_printed=True,
    )


def download_uniprot_proteome(
    proteome_id: str,
    output_path: str,
    organism_id: int | None = None,
    domain: str | None = None,
    max_retries: int = 3,
    retry_delay: float = 5.0,
) -> bool:
    """Download a proteome's FASTA: the reference proteome, else its reviewed entries, else all of it.

    A missing `organism_id` or `domain` is taken from the proteome's metadata.
    """
    if organism_id is None or domain is None:
        metadata = fetch_proteome_metadata(proteome_id)
        if organism_id is None:
            organism_id = metadata.organism_id
        if domain is None:
            domain = metadata.domain

    assert organism_id is not None, f"Missing organism_id for {proteome_id}"
    assert domain is not None, f"Missing domain for {proteome_id}"

    if download_proteome_fasta(
        proteome_id=proteome_id,
        organism_id=organism_id,
        domain=domain,
        output_path=output_path,
        max_retries=max_retries,
        retry_delay=retry_delay,
    ):
        return True

    print("  Reference proteome download failed; falling back to REST stream")
    if _download_uniprotkb_stream(
        proteome_id=proteome_id,
        query=f"(proteome:{proteome_id} AND reviewed:true)",
        output_path=output_path,
        max_retries=max_retries,
        retry_delay=retry_delay,
        label="REST reviewed",
    ):
        return True

    print("  Reviewed proteome unavailable; downloading full proteome")
    return _download_uniprotkb_stream(
        proteome_id=proteome_id,
        query=f"(proteome:{proteome_id})",
        output_path=output_path,
        max_retries=max_retries,
        retry_delay=retry_delay,
        label="REST full",
    )


def download_human_proteome(cache_dir: str) -> str:
    """The human reference proteome's gzipped FASTA in `cache_dir`, downloaded once."""
    os.makedirs(cache_dir, exist_ok=True)
    fasta_path = os.path.join(cache_dir, f"{HUMAN_PROTEOME_ID}.fasta.gz")
    if os.path.exists(fasta_path):
        print(f"Human proteome FASTA already exists: {fasta_path}")
        return fasta_path

    url = f"{REFERENCE_PROTEOMES_URL}/Eukaryota/{HUMAN_PROTEOME_ID}/{HUMAN_PROTEOME_ID}_{HUMAN_ORGANISM_ID}.fasta.gz"
    print("Downloading human proteome from UniProt...")
    print(f"  URL: {url}")

    response = requests.get(url, stream=True, timeout=300)
    response.raise_for_status()
    # Stream beside the final path and move it there only once it parses: the existence test above takes any file at
    # `fasta_path` for a complete one, so an interrupted transfer must never leave bytes there.
    partial_path = os.path.join(cache_dir, f"{HUMAN_PROTEOME_ID}.partial.fasta.gz")  # still `.gz`, which the reader keys on
    with open(partial_path, "wb") as handle:
        for chunk in response.iter_content(chunk_size=8192):
            handle.write(chunk)

    record_count = _count_fasta_records(partial_path)
    if record_count == 0:
        os.remove(partial_path)
        raise ValueError(f"UniProt answered an empty FASTA for {url}")
    os.replace(partial_path, fasta_path)
    print(f"  Downloaded {record_count} protein sequences")
    return fasta_path


def load_human_proteome(cache_dir: str) -> tuple[list[str], list[str]]:
    """The human reference proteome's identifiers and sequences, downloaded once into `cache_dir`."""
    fasta_path = download_human_proteome(cache_dir)

    ids: list[str] = []
    sequences: list[str] = []
    with open_text_maybe_gzip(fasta_path, mode="rt") as handle:
        for record in SeqIO.parse(handle, "fasta"):
            ids.append(record.id)
            sequences.append(str(record.seq))

    print(f"Loaded {len(sequences)} human proteome sequences")
    return ids, sequences


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    timeout_s: float,
    max_retries: int,
    backoff_base_s: float,
    backoff_max_s: float,
    **kwargs: Any,
) -> requests.Response:
    """One request, retried up to `max_retries` times on any error or a 429 or 5xx status.

    Attempt `k`, counting from 0, is followed by a wait of `min(backoff_max_s, backoff_base_s**k)`
    seconds, or what a `Retry-After` header asks within that cap (`foundry.retry`). The last failure
    is raised.
    """

    @retry(attempts=max_retries + 1, cap_seconds=backoff_max_s, when=lambda error: True,
           backoff=lambda attempt: backoff_base_s**attempt, sleep=lambda seconds: time.sleep(seconds))
    def attempt() -> requests.Response:
        response = session.request(method, url, timeout=timeout_s, **kwargs)
        if response.status_code in RETRYABLE_STATUS_CODES:
            raise requests.HTTPError(f"Retryable HTTP {response.status_code}: {response.text[:500]}", response=response)
        response.raise_for_status()
        return response

    return attempt()


def idmapping_pairs(session: requests.Session, ids: list[str], *, cfg: UniProtConfig) -> UniProtTable:
    """`ids` mapped by one UniProt ID-mapping job, as (`From`, `To`) rows in UniProt's order, rendering no entry.

    The plain mapping stream names each target by accession and so never truncates on an entry UniProt cannot
    render, as its result tables do (A0A140VKB8 and A0A178VUR4 on 2026-10-14). An obsolete accession maps to itself,
    and a merged one to an entry that may itself be inactive; `uniprotkb_table` leaves inactive entries out. A job
    UniProt fails is submitted again, and a stream that stops partway is read again, then split (`_whole_parts`).
    """

    def mapped(part: list[str]) -> tuple[tuple[str, ...], list[list[str]]] | None:
        job_id = idmapping_job(session, part, cfg=cfg)
        response = request_with_retry(
            session, "GET", f"{UNIPROT_BASE}/idmapping/stream/{job_id}", headers={"Accept": "application/json"},
            **{**_retry_settings(cfg), "timeout_s": cfg.timeout_s * 2},
        )
        try:
            payload = response.json()
        except ValueError:
            return None  # A stream cut partway is not JSON.
        if not isinstance(payload, dict) or "error" in payload or not isinstance(payload.get("results"), list):
            return None
        wanted = set(part)
        rows = [[row.get("from"), row.get("to")] for row in payload["results"]]
        if not all(source in wanted and isinstance(target, str) for source, target in rows):
            raise RuntimeError(f"UniProt ID mapping {job_id} answered for identifiers it was not asked for.")
        return ("From", "To"), rows

    return _whole_parts([list(ids)], mapped, session=session, cfg=cfg, what="ID mapping")


def uniprotkb_table(session: requests.Session, accessions: list[str], fields: str, *, cfg: UniProtConfig) -> UniProtTable:
    """UniProtKB's `fields` (`accession` first) for each active entry among the primary `accessions`, as TSV rows.

    Read by the accession lookup, `LOOKUP_BATCH` accessions a request, which leaves out an inactive entry instead of
    failing on it; a secondary accession finds nothing, so map identifiers with `idmapping_pairs` first. A table that
    stays truncated is split down to single accessions, and those UniProt still cannot render are reported.
    """
    if fields.split(",")[0] != "accession":
        raise ValueError(f"The accession lookup's fields must start with accession, so each row names its entry: {fields!r}")

    def looked_up(part: list[str]) -> tuple[tuple[str, ...], list[list[str]]] | None:
        response = request_with_retry(
            session, "GET", f"{UNIPROT_BASE}/uniprotkb/accessions",
            params={"accessions": ",".join(part), "format": "tsv", "fields": fields, "size": LOOKUP_BATCH},
            headers={"Accept": "text/plain"}, **_retry_settings(cfg),
        )
        if 'rel="next"' in response.headers.get("Link", ""):
            raise RuntimeError(f"UniProt split an accession lookup of {len(part)} accessions into pages.")
        return _whole_tsv_rows(response.text, "Entry", set(part))

    batches = [accessions[start : start + LOOKUP_BATCH] for start in range(0, len(accessions), LOOKUP_BATCH)]
    return _whole_parts(batches, looked_up, session=session, cfg=cfg, what="accession lookup")


def uniprotkb_entries(
    session: requests.Session, accessions: list[str], fields: str, *, cfg: UniProtConfig,
) -> tuple[list[dict[str, Any]], list[str]]:
    """UniProtKB's JSON entries, with `fields`, of each active entry among the primary `accessions`, and the accessions
    UniProt could not render.

    The accession lookup as `uniprotkb_table` runs it, in JSON for what the TSV fields leave out, such as the evidence
    code of each GO cross reference (`go_references`). A page that is not JSON, or answers for an entry not asked
    for, is read again and split as a truncated table is. The lookup left a merged and a demerged accession out on
    2026-10-17; should it ever answer one as the single-entry endpoint does, a document whose `entryType` is
    `Inactive` (with `inactiveReason` and no cross references), that document is left out here too.
    """
    if fields.split(",")[0] != "accession":
        raise ValueError(f"The accession lookup's fields must start with accession, so each entry names itself: {fields!r}")

    def looked_up(part: list[str]) -> tuple[tuple[str, ...], list[list[str]]] | None:
        response = request_with_retry(
            session, "GET", f"{UNIPROT_BASE}/uniprotkb/accessions",
            params={"accessions": ",".join(part), "format": "json", "fields": fields, "size": LOOKUP_BATCH},
            headers={"Accept": "application/json"}, **_retry_settings(cfg),
        )
        if 'rel="next"' in response.headers.get("Link", ""):
            raise RuntimeError(f"UniProt split an accession lookup of {len(part)} accessions into pages.")
        try:
            payload = response.json()
        except ValueError:
            return None  # A stream cut partway is not JSON.
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            return None
        wanted = set(part)
        entries = payload["results"]
        if not all(isinstance(entry, dict) and entry.get("primaryAccession") in wanted for entry in entries):
            return None
        return ("Entry", "JSON"), [[entry["primaryAccession"], json.dumps(entry, sort_keys=True)]
                                   for entry in entries if entry.get("entryType") != INACTIVE_ENTRY_TYPE]

    batches = [accessions[start : start + LOOKUP_BATCH] for start in range(0, len(accessions), LOOKUP_BATCH)]
    table = _whole_parts(batches, looked_up, session=session, cfg=cfg, what="accession lookup")
    return [json.loads(document) for _, document in table.rows], table.unrenderable


def go_references(entry: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Each GO cross reference of a UniProtKB JSON entry fetched with the `go` field: its term id (`GO:0005515`), its
    aspect letter (`P`, `F` or `C`, from the `GoTerm` property) and its evidence code (`IDA`, `IPI`, ..., the part of
    `GoEvidenceType` before the source), in the entry's order. A reference missing either property raises."""
    references = []
    for reference in entry.get("uniProtKBCrossReferences", ()):
        if reference.get("database") != "GO":
            continue
        properties = {item["key"]: item["value"] for item in reference.get("properties", ())}
        if "GoTerm" not in properties or "GoEvidenceType" not in properties:
            raise ValueError(f"{entry.get('primaryAccession')}: GO reference {reference.get('id')} lacks its aspect or evidence.")
        aspect = properties["GoTerm"].split(":", 1)[0]
        if aspect not in ("P", "F", "C"):
            raise ValueError(f"{entry.get('primaryAccession')}: GO reference {reference['id']} has aspect {aspect!r}.")
        references.append((reference["id"], aspect, properties["GoEvidenceType"].split(":", 1)[0]))
    return references


def _whole_tsv_rows(text: str, key_column: str, wanted: set[str]) -> tuple[tuple[str, ...], list[list[str]]] | None:
    """A TSV table's header and data rows when UniProt sent it whole, else None.

    UniProt ends a stream that fails partway with blank lines and an error line, still HTTP 200. A whole table ends a
    line, and every row has the header's field count and a requested identifier in `key_column`, the first column.
    A header that names another first column is a changed format, not a truncation, and raises.
    """
    if not text.endswith("\n"):
        return None
    lines = text[:-1].split("\n")
    header = tuple(lines[0].split("\t"))
    if header[0] != key_column:
        if lines[0] == "" or lines[0].startswith("Error"):
            return None
        raise ValueError(f"UniProt's table starts with {header[:3]}, not {key_column!r}.")
    rows = [line.split("\t") for line in lines[1:]]
    if not all(len(row) == len(header) and row[0] in wanted for row in rows):
        return None
    return header, rows


def uniprot_idmapping(
    session: requests.Session,
    ids: list[str],
    *,
    cfg: UniProtConfig,
    include_organism_name: bool = False,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Map `ids` through UniProt's ID mapping service, then read each mapped entry's sequence.

    Returns input accession to primary accession, primary accession to sequence, and, with
    `include_organism_name`, primary accession to organism name. An identifier mapped to an
    inactive entry maps to that entry, without a sequence; one mapped to several entries maps to
    the last active one. A truncated or failed response is never read as a short one: it is read
    again, split, or raised (`idmapping_pairs`, `uniprotkb_table`), and identifiers UniProt cannot
    render are printed to stderr and left out.
    """
    if len(ids) == 0:
        return {}, {}, {}

    pairs = idmapping_pairs(session, ids, cfg=cfg)
    fields = "accession,sequence,organism_name" if include_organism_name else "accession,sequence"
    entries = uniprotkb_table(session, sorted({target for _, target in pairs.rows}), fields, cfg=cfg)
    for name, table in (("identifiers", pairs), ("entries", entries)):
        if table.unrenderable:
            print(f"Warning: UniProt could not render {len(table.unrenderable)} {name}, left unmapped: "
                  f"{', '.join(table.unrenderable)}", file=sys.stderr, flush=True)

    primary_to_seq: dict[str, str] = {}
    primary_to_org: dict[str, str] = {}
    for row in entries.rows:
        values = dict(zip(entries.header, row, strict=True))
        if values.get("Sequence"):
            primary_to_seq[row[0]] = values["Sequence"]
        if include_organism_name and values.get("Organism"):
            primary_to_org[row[0]] = values["Organism"]

    active = {row[0] for row in entries.rows}
    id_to_primary: dict[str, str] = {}
    for source, target in pairs.rows:
        if source not in id_to_primary or target in active or id_to_primary[source] not in active:
            id_to_primary[source] = target
    return id_to_primary, primary_to_seq, primary_to_org


def _retry_settings(cfg: UniProtConfig) -> dict[str, float]:
    return {"timeout_s": cfg.timeout_s, "max_retries": cfg.max_retries, "backoff_base_s": cfg.backoff_base_s,
            "backoff_max_s": cfg.backoff_max_s}


def idmapping_job(session: requests.Session, ids: list[str], *, cfg: UniProtConfig) -> str:
    """The id of a finished ID-mapping job for `ids`, whose results any of UniProt's result endpoints then reads.

    A job UniProt fails is submitted again, on a new connection: UniProt fails a job when its backend does, answering
    the status with HTTP 400 and `jobStatus` ERROR (a 503 inside on 2026-10-14), and submitting the same identifiers
    again reruns it. The status is polled every `cfg.poll_s` seconds without retrying a 4xx, so an ERROR is seen at once.
    """
    for attempt in range(cfg.job_attempts):
        job_id = request_with_retry(
            session, "POST", f"{UNIPROT_BASE}/idmapping/run",
            data={"from": cfg.idmapping_from, "to": cfg.idmapping_to, "ids": ",".join(ids)},
            headers={"Accept": "application/json"}, **_retry_settings(cfg),
        ).json()["jobId"]
        while True:
            status = _job_status(session, job_id, cfg)
            if status.status_code == 303:
                return job_id
            payload = status.json()
            job_status = payload.get("jobStatus")
            if job_status == "FINISHED" or "results" in payload or "failedIds" in payload:
                return job_id
            if job_status == "ERROR":
                break
            if status.status_code >= 400 or job_status not in ("NEW", "RUNNING"):
                raise RuntimeError(f"UniProt ID mapping {job_id} failed: HTTP {status.status_code} {status.text[:500]}")
            time.sleep(cfg.poll_s)
        print(f"UniProt failed ID-mapping job {job_id} for {len(ids)} identifiers (attempt {attempt + 1}/"
              f"{cfg.job_attempts}); submitting it again", file=sys.stderr, flush=True)
        session.close()
        time.sleep(cfg.pause_s * (attempt + 1))
    raise RuntimeError(f"UniProt failed the ID-mapping job for {len(ids)} identifiers {cfg.job_attempts} times.")


def _job_status(session: requests.Session, job_id: str, cfg: UniProtConfig) -> requests.Response:
    """One status answer, its redirect not followed, retried only on a 429, a 5xx or a failed connection."""

    @retry(attempts=cfg.max_retries + 1, cap_seconds=cfg.backoff_max_s, when=transient,
           backoff=lambda attempt: cfg.backoff_base_s**attempt, sleep=lambda seconds: time.sleep(seconds))
    def attempt() -> requests.Response:
        response = session.request("GET", f"{UNIPROT_BASE}/idmapping/status/{job_id}", timeout=cfg.timeout_s,
                                   headers={"Accept": "application/json"}, allow_redirects=False)
        if response.status_code in RETRYABLE_STATUS_CODES:
            raise requests.HTTPError(f"Retryable HTTP {response.status_code}: {response.text[:500]}", response=response)
        return response

    return attempt()


def _whole_parts(
    parts: list[list[str]],
    fetch: Callable[[list[str]], tuple[tuple[str, ...], list[list[str]]] | None],
    *,
    session: requests.Session,
    cfg: UniProtConfig,
    what: str,
) -> UniProtTable:
    """Every part's table, fetched whole: each part is tried `cfg.stream_attempts` times, then split in halves.

    `fetch` answers one part's header and rows, or None when the table stopped partway. Between attempts the session
    drops its kept-alive connections. UniProt truncates deterministically at an entry it cannot render, so halving
    isolates each such identifier, which is reported in `unrenderable`. Rows keep the parts' order.
    """
    header: tuple[str, ...] = ()
    rows: list[list[str]] = []
    unrenderable: list[str] = []
    pending = list(reversed([part for part in parts if part]))
    with tqdm(total=sum(len(part) for part in parts), desc=f"UniProt {what}", file=sys.stderr, mininterval=5,
              disable=len(parts) < 2) as progress:
        while pending:
            part = pending.pop()
            table = None
            for attempt in range(cfg.stream_attempts):
                table = fetch(part)
                if table is not None:
                    break
                print(f"UniProt {what}: truncated table for {len(part)} identifiers (attempt {attempt + 1}/"
                      f"{cfg.stream_attempts})", file=sys.stderr, flush=True)
                session.close()
                time.sleep(cfg.pause_s * (attempt + 1))
            if table is None:
                if len(part) == 1:
                    unrenderable.append(part[0])
                    progress.update(1)
                else:
                    half = len(part) // 2
                    pending += [part[half:], part[:half]]
                continue
            if header and table[0] != header:
                raise RuntimeError(f"UniProt {what} changed its header from {header} to {table[0]}.")
            header = table[0]
            rows += table[1]
            progress.update(len(part))
    return UniProtTable(header, rows, unrenderable)


def resolve_uniprot_sequences(
    all_ids: set[str],
    *,
    cfg: UniProtConfig,
    idmapping_chunk_size: int,
    cache_dir: Path,
    seq_chunk_size: int | None = None,
    include_organism_name: bool = False,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Map every identifier in `all_ids` not yet in the cache, in chunks on `cfg.max_workers` threads.

    Returns original identifier to primary accession, primary accession to sequence, and, with
    `include_organism_name`, primary accession to organism name, each merged into and saved back
    to its pickle in `cache_dir`. A chunk that fails is reported and skipped, so its identifiers
    stay unmapped until a rerun. `seq_chunk_size` is accepted and unused.
    """
    id_map_path = cache_dir / "id_to_primary.pkl"
    seq_path = cache_dir / "primary_to_seq.pkl"
    org_path = cache_dir / "primary_to_org.pkl"

    id_to_primary: dict[str, str] = _cache_load(id_map_path, default={})
    primary_to_seq: dict[str, str] = _cache_load(seq_path, default={})
    primary_to_org: dict[str, str] = _cache_load(org_path, default={}) if include_organism_name else {}

    missing_ids = [accession for accession in sorted(all_ids) if accession not in id_to_primary]
    if not missing_ids:
        return id_to_primary, primary_to_seq, primary_to_org

    print(f"Resolving {len(missing_ids):,} missing accessions via UniProt ID Mapping...")
    chunks = [missing_ids[i : i + idmapping_chunk_size] for i in range(0, len(missing_ids), idmapping_chunk_size)]
    cache_lock = Lock()

    def process_chunk(chunk: list[str]) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        return uniprot_idmapping(requests.Session(), chunk, cfg=cfg, include_organism_name=include_organism_name)

    with ThreadPoolExecutor(max_workers=cfg.max_workers) as executor:
        futures = {executor.submit(process_chunk, chunk): chunk for chunk in chunks}
        for future in tqdm(as_completed(futures), total=len(futures), desc="UniProt ID Mapping"):
            try:
                chunk_map, chunk_seqs, chunk_orgs = future.result()
            except Exception as error:  # noqa: broad-except - failed chunks remain unmapped for a later retry
                print(f"Warning: Chunk failed with {error}")
                continue
            with cache_lock:
                id_to_primary.update(chunk_map)
                primary_to_seq.update(chunk_seqs)
                if include_organism_name:
                    primary_to_org.update(chunk_orgs)

    _cache_save(id_map_path, id_to_primary)
    _cache_save(seq_path, primary_to_seq)
    if include_organism_name:
        _cache_save(org_path, primary_to_org)
    return id_to_primary, primary_to_seq, primary_to_org


def _extract_domain_from_lineage(lineage: str) -> str:
    """Eukaryota, Bacteria, Archaea, or Viruses, from a lineage string; Eukaryota, with a warning, if none match."""
    lineage_lower = lineage.lower()
    if "eukaryota" in lineage_lower:
        return "Eukaryota"
    if "bacteria" in lineage_lower:
        return "Bacteria"
    if "archaea" in lineage_lower:
        return "Archaea"
    if "virus" in lineage_lower or "viridae" in lineage_lower:
        return "Viruses"
    print("  Warning: Could not determine domain from lineage, defaulting to Eukaryota")
    return "Eukaryota"


def _request_json(url: str, timeout: float = 30.0) -> dict[str, Any]:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    document = response.json()
    assert isinstance(document, dict), f"Expected JSON object from {url}, got {type(document)}"
    return document


def _normalize_lineage(lineage_field: Any) -> str:
    """A lineage as one semicolon-separated string, from a string, a list of names, or a list of taxa."""
    if isinstance(lineage_field, str):
        return lineage_field
    if isinstance(lineage_field, list):
        if len(lineage_field) == 0:
            return ""
        first = lineage_field[0]
        if isinstance(first, str):
            return ";".join(str(item) for item in lineage_field)
        if isinstance(first, dict):
            names: list[str] = []
            for item in lineage_field:
                if "scientificName" in item:
                    names.append(item["scientificName"])
                elif "name" in item:
                    names.append(item["name"])
                else:
                    raise KeyError("Lineage entry missing scientificName/name")
            return ";".join(names)
    raise TypeError(f"Unsupported lineage format: {type(lineage_field)}")


def _extract_lineage_from_metadata(metadata: dict[str, Any]) -> str:
    """The lineage from any of the places UniProt's JSON shapes put it, or "" when none holds one."""
    if "lineage" in metadata:
        return _normalize_lineage(metadata["lineage"])
    for container in ("organism", "taxonomy"):
        if container in metadata and isinstance(metadata[container], dict):
            section = metadata[container]
            if "lineage" in section:
                return _normalize_lineage(section["lineage"])
            if "taxonLineage" in section:
                return _normalize_lineage(section["taxonLineage"])
    if "taxonLineage" in metadata:
        return _normalize_lineage(metadata["taxonLineage"])
    return ""


def _fetch_taxonomy_lineage(organism_id: int) -> str:
    return _extract_lineage_from_metadata(_request_json(f"{UNIPROT_BASE}/taxonomy/{organism_id}.json"))


def _count_fasta_records(fasta_path: str) -> int:
    with open_text_maybe_gzip(fasta_path, mode="rt") as handle:
        return sum(1 for _ in SeqIO.parse(handle, "fasta"))


def _download_uniprotkb_stream(
    proteome_id: str,
    query: str,
    output_path: str,
    max_retries: int = 3,
    retry_delay: float = 5.0,
    label: str | None = None,
) -> bool:
    """Download the canonical entries matching `query` from UniProtKB's REST stream as gzipped FASTA."""
    params = {
        "compressed": "true",
        "download": "true",
        "format": "fasta",
        "includeIsoform": "false",
        "query": query,
    }
    source = label if label is not None else "REST API"
    return _download_fasta(
        f"{UNIPROT_BASE}/uniprotkb/stream",
        params,
        output_path,
        f"{proteome_id} from {source}",
        "sequences",
        max_retries,
        retry_delay,
        url_printed=False,
    )


def _download_fasta(
    url: str,
    params: dict[str, str] | None,
    output_path: str,
    description: str,
    count_label: str,
    max_retries: int,
    retry_delay: float,
    *,
    url_printed: bool,
) -> bool:
    """Fetch and validate a FASTA before replacing `output_path`, retrying with backoff.

    Partial transfers resume within these retries. Each source gets its own staging
    directory, so a fallback cannot append bytes from a different source.
    """
    if max_retries <= 0:
        return False
    destination = Path(output_path)
    request_url = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    delay = retry_delay
    try:
        with tempfile.TemporaryDirectory(prefix=".uniprot-", dir=destination.parent) as staging:
            candidate = Path(staging) / destination.name
            for attempt in range(max_retries):
                try:
                    print(f"Downloading {description} (attempt {attempt + 1}/{max_retries})...")
                    if url_printed:
                        print(f"  URL: {url}")
                    download_file(request_url, candidate, timeout_seconds=300)
                    record_count = _count_fasta_records(str(candidate))
                    if record_count == 0:
                        raise ValueError("Empty FASTA file")
                    candidate.replace(destination)
                    print(f"  Downloaded {record_count} {count_label}")
                    return True
                except Exception as error:  # noqa: broad-except - preserve the public boolean failure contract
                    # The public API reports exhausted transport or FASTA errors as False.
                    # Reject complete but invalid candidates; retain resumable partial bytes.
                    print(f"  Download failed: {error}")
                    candidate.unlink(missing_ok=True)
                    if attempt < max_retries - 1:
                        print(f"  Retrying in {delay} seconds...")
                        time.sleep(delay)
                        delay *= 2
                    else:
                        print(f"  Failed after {max_retries} attempts")
    except OSError as error:
        print(f"  Download failed: {error}")
    return False


def _cache_load(path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    return read_pickle_dict(path)


def _cache_save(path: Path, payload: dict[str, Any]) -> None:
    assert isinstance(payload, dict), "Cache payload must be a dict."
    write_pickle_dict_atomic(path, payload)


__all__ = [
    "DEFAULT_PROTEOMES",
    "HUMAN_ORGANISM_ID",
    "HUMAN_PROTEOME_ID",
    "ProteomeInfo",
    "UNIPROT_BASE",
    "INACTIVE_ENTRY_TYPE",
    "LOOKUP_BATCH",
    "UniProtConfig",
    "UniProtTable",
    "download_human_proteome",
    "download_proteome_fasta",
    "download_uniprot_proteome",
    "fetch_proteome_metadata",
    "go_references",
    "idmapping_job",
    "idmapping_pairs",
    "load_human_proteome",
    "load_proteome_metadata_json",
    "parse_id_fields",
    "parse_proteome_tsv",
    "parse_uniprot_id",
    "request_with_retry",
    "resolve_uniprot_sequences",
    "uniprot_idmapping",
    "uniprotkb_entries",
    "uniprotkb_table",
]
