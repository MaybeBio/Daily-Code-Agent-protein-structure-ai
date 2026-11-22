# Results

Pretraining corpus: AlphaFold, 26,057 structures. Fine-tuning: MegaScale, 271,231 single mutations over
298 proteins, ThermoMPNN splits, test set 28 proteins.

A difference under 0.012 pooled or 0.016 per-protein median is a tie: that is roughly two
standard deviations of arm A across seeds, fixed before any pretrained arm was run.

## Main table, frozen encoder

Arm A has nothing to freeze, so it appears only in the full table below.

| arm       |   seeds | test_pooled_spearman   | test_per_protein_median_spearman   | test_rmse     |
|:----------|--------:|:-----------------------|:-----------------------------------|:--------------|
| B  vector |       3 | 0.543 ± 0.012          | 0.563 ± 0.029                      | 0.894 ± 0.021 |
| C  letter |       3 | 0.639 ± 0.003          | 0.698 ± 0.004                      | 0.784 ± 0.025 |
| D  both   |       3 | 0.636 ± 0.002          | 0.705 ± 0.005                      | 0.781 ± 0.012 |

## Full fine-tuning

| arm     |   seeds | test_pooled_spearman   | test_per_protein_median_spearman   | test_rmse     |
|:--------|--------:|:-----------------------|:-----------------------------------|:--------------|
| A  none |       3 | 0.605 ± 0.008          | 0.643 ± 0.011                      | 0.802 ± 0.011 |

## Embeddings

Effective rank at the end of pretraining, measured on 80000 held-out residues.
Rank is only comparable between runs measured the same way, and as the main table shows,
it does not predict which arm transfers best.

| arm       |   seeds | val_effective_rank   | val_letter_accuracy   |
|:----------|--------:|:---------------------|:----------------------|
| B  vector |       3 | 108.211 ± 2.399      | nan                   |
| C  letter |       3 | 64.621 ± 0.810       | 0.353 ± 0.003         |
| D  both   |       3 | 65.284 ± 0.587       | 0.350 ± 0.003         |

## Cost

Seconds per pretraining epoch.

| arm       |   seeds | seconds        |
|:----------|--------:|:---------------|
| B  vector |       3 | 17.568 ± 0.418 |
| C  letter |       3 | 14.377 ± 1.030 |
| D  both   |       3 | 17.570 ± 1.714 |

## Figures

- `figures/effective_rank_alphafold.png` — effective rank through pretraining
- `figures/arm_comparison_alphafold.png` — every seed's test score, by arm
