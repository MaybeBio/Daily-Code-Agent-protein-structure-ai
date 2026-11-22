# Final Tables

*Test AUC is the headline metric. Precision/recall/F1 are omitted because the dot-product decoder predicts 'interaction' for nearly every pair at the 0.5 threshold in several GCN settings (precision 0.5, recall 1.0), so those numbers are degenerate.*

**Table 1. Link-prediction test AUC on PrimeKG (5 seeds).**

| Model | AUC (Random) | AUC (Cold-protein) |
|---|---|---|
| Structure only | 0.882 ± 0.001 | 0.753 ± 0.011 |
| GCN + ESM-2 | 0.890 ± 0.002 | 0.805 ± 0.007 |
| GCN + Classical | 0.890 ± 0.001 | 0.828 ± 0.004 |
| RF (Classical) | 0.822 ± 0.002 | 0.678 ± 0.006 |

**Table 2. Link-prediction test AUC on STRING v12.0 physical links (score ≥ 700, proteins shared with PrimeKG; 5 seeds).**

| Model | AUC (Random) | AUC (Cold-protein) |
|---|---|---|
| Structure only | 0.894 ± 0.005 | 0.597 ± 0.016 |
| GCN + ESM-2 | 0.855 ± 0.021 | 0.780 ± 0.016 |
| GCN + Classical | 0.824 ± 0.003 | 0.780 ± 0.011 |
| RF (Classical) | 0.836 ± 0.002 | 0.721 ± 0.008 |

**Table 3. Paired Wilcoxon signed-rank tests on test AUC, PrimeKG (exact p-values). With 5 pairs the smallest attainable two-sided p is 0.0625.**

| Split | Comparison (B vs A) | Mean ΔAUC | B wins /n | p (two-sided) | p (one-sided, B>A) |
|---|---|---|---|---|---|
| Random Split | Sequence + Structure vs Structure Only | +0.0086 | 5/5 | 0.0625 | 0.0312 |
| Random Split | Classical + Structure vs Structure Only | +0.0085 | 5/5 | 0.0625 | 0.0312 |
| Random Split | Sequence + Structure vs Classical + Structure | +0.0001 | 2/5 | 1.0000 | 0.5000 |
| Cold-Protein Split | Sequence + Structure vs Structure Only | +0.0518 | 5/5 | 0.0625 | 0.0312 |
| Cold-Protein Split | Classical + Structure vs Structure Only | +0.0750 | 5/5 | 0.0625 | 0.0312 |
| Cold-Protein Split | Sequence + Structure vs Classical + Structure | -0.0232 | 0/5 | 0.0625 | 1.0000 |

**Table 4. Paired Wilcoxon signed-rank tests on test AUC, STRING (exact p-values). With 5 pairs the smallest attainable two-sided p is 0.0625.**

| Split | Comparison (B vs A) | Mean ΔAUC | B wins /n | p (two-sided) | p (one-sided, B>A) |
|---|---|---|---|---|---|
| Random Split | Sequence + Structure vs Structure Only | -0.0386 | 0/5 | 0.0625 | 1.0000 |
| Random Split | Classical + Structure vs Structure Only | -0.0695 | 0/5 | 0.0625 | 1.0000 |
| Random Split | Sequence + Structure vs Classical + Structure | +0.0309 | 5/5 | 0.0625 | 0.0312 |
| Cold-Protein Split | Sequence + Structure vs Structure Only | +0.1826 | 5/5 | 0.0625 | 0.0312 |
| Cold-Protein Split | Classical + Structure vs Structure Only | +0.1827 | 5/5 | 0.0625 | 0.0312 |
| Cold-Protein Split | Sequence + Structure vs Classical + Structure | -0.0001 | 2/5 | 1.0000 | 0.5938 |

**Table 5. PrimeKG PPI network statistics.**

| Statistic | value |
|---|---|
| nodes | 17,328 |
| edges | 311,451 |
| density | 0.002075 |
| degree_mean | 35.95 |
| degree_median | 18 |
| degree_std | 73.41 |
| degree_max | 5,191 |
| avg_clustering | 0.1126 |
| transitivity | 0.04566 |
| n_connected_components | 3 |
| largest_cc_size | 17,323 |
| largest_cc_fraction | 0.9997 |
| isolated_nodes | 0 |

**Table 6. Top-10 hub proteins by degree (PrimeKG).**

| rank | uniprot | gene_symbol | protein_name | degree |
|---|---|---|---|---|
| 1 | P0CG48 | UBC | Polyubiquitin-C | 5191 |
| 2 | P14921 | ETS1 | Protein C-ets-1 | 1465 |
| 3 | P23769 | GATA2 | Endothelial transcription factor GATA-2 | 1334 |
| 4 | P49711 | CTCF | Transcriptional repressor CTCF | 1283 |
| 5 | P10275 | AR | Androgen receptor | 1097 |
| 6 | P01106 | MYC | Myc proto-oncogene protein | 1057 |
| 7 | Q09472 | EP300 | Histone acetyltransferase p300 | 1047 |
| 8 | P05067 | APP | Amyloid-beta precursor protein | 941 |
| 9 | O60216 | RAD21 | Double-strand-break repair protein rad21 homolog | 919 |
| 10 | P18146 | EGR1 | Early growth response protein 1 | 859 |

**Table 7. Homology audit of the cold-protein test set (Smith-Waterman identity to nearest training protein).**

| Cold test proteins | Mean identity | Median identity | % < 30% | % < 40% | % > 70% |
|---|---|---|---|---|---|
| 500 | 0.234 | 0.217 | 91.2 | 97.6 | 0.4 |

**Table 8. STRING graph construction.**

| step | value |
|---|---|
| primekg_proteins | 17328 |
| string_link_rows_total | 1477610 |
| string_link_rows_score>=700 | 173038 |
| string_ids_mapped_to_primekg | 17369 |
| string_ids_ambiguous(>1 accession) | 6 |
| final_undirected_edges | 78423 |
| final_nodes | 10272 |
| primekg_proteins_missing_from_string_graph | 7056 |
