---
id: foundry.downloads.uniprot
kind: library_module
status: active
aliases: [foundry.downloads.uniprot]
---
# foundry.downloads.uniprot

UniProt access: identifier parsing, proteome metadata and FASTA downloads, and ID mapping.

| Name | Does |
|---|---|
| `parse_uniprot_id(raw_id)`, `parse_id_fields(raw_id)` | The accession, and the gene symbol, in `sp|P08238|HS90B_HUMAN` or a plain identifier |
| `ProteomeInfo`, `DEFAULT_PROTEOMES`, `HUMAN_PROTEOME_ID`, `HUMAN_ORGANISM_ID` | A proteome's identifier, organism, protein count, and domain; the eight reference proteomes synth serves |
| `fetch_proteome_metadata`, `load_proteome_metadata_json`, `parse_proteome_tsv` | Proteome metadata from the REST API, a JSON file, or UniProt's proteome table |
| `download_proteome_fasta`, `download_uniprot_proteome` | A reference proteome's FASTA from the FTP site; failing that, the reviewed entries from the REST stream; failing that, all of them |
| `download_human_proteome`, `load_human_proteome` | The human reference proteome, downloaded once into a cache directory |
| `UniProtConfig`, `uniprot_idmapping`, `resolve_uniprot_sequences` | Accessions mapped to primary accessions, sequences, and organisms, in parallel chunks cached as pickles |
| `idmapping_job(session, ids, cfg=)` | A finished ID-mapping job's id; a job UniProt fails is submitted again |
| `idmapping_pairs(session, ids, cfg=)` | One ID-mapping job's (`From`, `To`) pairs from the plain mapping stream, which renders no entry |
| `uniprotkb_table(session, accessions, fields, cfg=)` | Any `fields` of the active entries among primary accessions, by the accession lookup, 500 a request (`LOOKUP_BATCH`) |
| `uniprotkb_entries(session, accessions, fields, cfg=)` | The same lookup in JSON: the active entries' documents and the accessions UniProt could not render, for what the TSV fields leave out |
| `go_references(entry)` | A JSON entry's GO cross references as (term id, aspect letter, evidence code), the evidence the TSV `go_*` fields drop |
| `UniProtTable` | What both return: the header, the rows of tables that came back whole, and the identifiers UniProt could not render |
| `request_with_retry` | One HTTP request retried on errors and 429 or 5xx statuses with capped exponential backoff |

## Truncated tables

On 2026-10-14 UniProt answered HTTP 200 with tables that stopped partway, ending in blank lines and
`Error encountered when streaming data. Please try again later.` The cause was an entry its renderer
cannot render: A0A140VKB8 (merged into Q7Z6W1) and A0A178VUR4. Any results table, page or JSON
results stream holding one stops at the same point on every retry and every connection; a job
holding A0A140VKB8 among others returned no rows at all. Until then `uniprot_idmapping` read such a
table as a short one (the error line even parsed as a row), and `resolve_uniprot_sequences` cached it.

So `uniprot_idmapping` and Atlas v3's balanced builder (`atlas.v3.balanced`, its GO stage) both map
identifiers with `idmapping_pairs`, which renders nothing (an obsolete accession maps to itself),
then read the entries with `uniprotkb_table`, which leaves inactive entries out. Every table is
checked whole before it is read: it ends a line, each row has the header's field count, and each
row names a requested identifier. A truncated table is fetched again on a new connection
(`stream_attempts`), then split in halves down to the identifiers UniProt still cannot render,
which are returned in `unrenderable`; `uniprot_idmapping`, whose return value has no place for
them, prints them to stderr. A job whose status answers HTTP 400 with `jobStatus` ERROR (a backend
503) is submitted again (`job_attempts`); its status is polled without retrying a 4xx. A header
that names another first column raises, since it is a changed format, not a truncation. The
Atlas builder, which needed the same checks first, held its own copy until then.

Atlas v3's pinned acquisition (`atlas.v3.source_uniprot`) runs its jobs through `idmapping_job`
since the same day; until then its own runner stopped at the first ERROR status. It keeps its
paginated result pages, its culprit search after the last intact row and its merge following,
because it pins UniProt's own page bytes and the compiler reads those pins back; its module
docstring records why. A chunk holding A0A140VKB8 cost it about two minutes of page refetches
and culprit search on 2026-10-14, where `uniprotkb_table` skips the inactive entry at once.

Promoted on 2026-09-24 from the `uniprot.py` that DatasetDev and synth each held, which
differed only in imports and synth's public name for `request_with_retry`, and from Atlas's
`utils/uniprot.py`, which held the two identifier parsers. Each is now a module that imports its
names from here. Atlas's `utils/uniprot_proteome.py`, a different proteome fetcher with one
consumer, stays in Atlas.

FASTA downloads use the shared HTTPS downloader. They resume partial transfers within
one source's retries, validate the staged FASTA, then replace the destination. Failed
downloads leave an existing destination untouched. Each fallback source has a separate
staging directory; partial bytes are removed when its retries finish, so later sources
and later calls start independently.

## Known issues

These are behaviors every copy had, kept as they were.

- `uniprot_idmapping` maps an identifier with several entries (a secondary accession that
  several entries share, such as P02023) to the last active one UniProt lists, which need not
  be the one from the identifier's own organism.
- `resolve_uniprot_sequences` reports a failed chunk and skips it, so its accessions stay
  unmapped until a rerun asks for them again; so do identifiers UniProt cannot render. An
  identifier mapped to an inactive entry is cached as mapped, without a sequence.
- `request_with_retry` retries every failure, a 4xx included, so a 404 costs its whole backoff.
- `download_proteome_fasta` and `download_uniprot_proteome` report failure by returning False,
  and print their progress rather than logging it.

Tests: `tests/tier1_unit/test_uniprot.py`, with UniProt stood in for; nothing reaches the network.
