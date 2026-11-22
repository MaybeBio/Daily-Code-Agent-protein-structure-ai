# Results

Pretraining corpus: SCOPe, 11,566 domains. Fine-tuning: MegaScale, 271,231 single mutations over
298 proteins, ThermoMPNN splits, test set 28 proteins.

A difference under 0.012 pooled or 0.016 per-protein median is a tie: that is roughly two
standard deviations of arm A across seeds, fixed before any pretrained arm was run.

## Main table, frozen encoder

Arm A has nothing to freeze, so it appears only in the full table below.

| arm       |   seeds | test_pooled_spearman   | test_per_protein_median_spearman   | test_rmse     |
|:----------|--------:|:-----------------------|:-----------------------------------|:--------------|
| B  vector |       3 | 0.506 ± 0.023          | 0.539 ± 0.018                      | 0.903 ± 0.015 |
| C  letter |       3 | 0.640 ± 0.005          | 0.688 ± 0.005                      | 0.767 ± 0.006 |
| D  both   |       3 | 0.643 ± 0.008          | 0.692 ± 0.010                      | 0.768 ± 0.005 |

## Full fine-tuning

| arm     |   seeds | test_pooled_spearman   | test_per_protein_median_spearman   | test_rmse     |
|:--------|--------:|:-----------------------|:-----------------------------------|:--------------|
| A  none |       3 | 0.605 ± 0.008          | 0.643 ± 0.011                      | 0.802 ± 0.011 |

## Embeddings

Effective rank at the end of pretraining, measured on 80275 held-out residues.
Rank is only comparable between runs measured the same way, and as the main table shows,
it does not predict which arm transfers best.

| arm       |   seeds | val_effective_rank   | val_letter_accuracy   |
|:----------|--------:|:---------------------|:----------------------|
| B  vector |       3 | 74.157 ± 2.273       | nan                   |
| C  letter |       3 | 61.868 ± 0.512       | 0.267 ± 0.003         |
| D  both   |       3 | 62.580 ± 0.252       | 0.266 ± 0.004         |

## Cost

Seconds per pretraining epoch.

| arm       |   seeds | seconds       |
|:----------|--------:|:--------------|
| B  vector |       3 | 7.551 ± 0.663 |
| C  letter |       3 | 6.153 ± 0.848 |
| D  both   |       3 | 7.660 ± 0.491 |

## Figures

- `figures/effective_rank_scope.png` — effective rank through pretraining
- `figures/arm_comparison_scope.png` — every seed's test score, by arm
