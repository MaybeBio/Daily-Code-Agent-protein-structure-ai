# AlphaFold pretraining corpus

- structures: **26,057**
- attempted: 30,000 accessions (86.9% usable)
- residues: 4,087,492
- length: min 30, median 157, max 256
- mean pLDDT: 90.2 (filter was >= 70)
- shards: 15

Skipped, by reason:

- low_plddt: 1,934
- http_404: 1,130
- http_429: 878
- bad_length: 1

Sampled with seed 0 from `alphafold_candidates.txt`, which is Swiss-Prot filtered
to 30-256 residues and screened against all 298 MegaScale proteins with MMseqs2.
Accession list: `alphafold_ids.txt`.
