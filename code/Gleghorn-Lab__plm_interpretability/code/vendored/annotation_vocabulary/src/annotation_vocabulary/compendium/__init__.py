"""The annotation compendium: one snapshot-pinned compile of UniProtKB and related resources, of which every task dataset is a view.

Logan, 2026-10-20 (docs/decisions/representation/annotation_vocabulary/2026-10-20_annotation_compendium.md). The pool is Swiss-Prot
and the TrEMBL entries of Swiss-Prot quality (an experimental GOA assertion, annotation score 4 or 5, or protein existence 1), one
row per distinct sequence of at most 2,046 residues. Every assertion keeps its evidence code and tier (experimental, signature,
curated, guard); measurements stay raw; ontologies give a typed edge table; an eight-level MMseqs2 cascade gives the clusters; one
global 85/5/8/2 split serves the whole-vocabulary models, and each task dataset is a view (a filter, a target rule, negatives and
the split it inherits or makes).

The tables (`tables.py` holds their schemas): `entries`, `assertions` and `measurement_texts` per UniProtKB accession as read,
then `proteins`, pooled `assertions`, `hierarchy`, `clusters`, `split` and `vocabulary` per distinct sequence.
"""
