# Results for the report (real values)

Source of every number: the Kaggle notebooks in `template-finder/` (methods/, selector/, data/, rnapro/) (details in `PROGRESS_LOG.md`).

## Setup in one paragraph

1,884 RNA chains: 1,549 train, 159 validation, 176 test (test not used yet). "Train (OOF)" = the 1,549
train chains, each scored by a selector that never saw its family (5 family-held-out folds).
"Validation" = the 159 validation chains, selector trained on all train chains. Template library =
the 1,549 train chains. **Date filter** = a chain may only use templates released before it (main,
legal setting); every number below uses it unless stated otherwise.

Metrics (template labels = US-align TM-score of template vs query, normalised by query length):
- **best TM@k**: TM-score of the best template among the top k, averaged over all chains.
- **hit@k**: share of chains with a template of TM ≥ 0.45 in the top k, counted over chains that
  have such a template in the library at all.
- RNAPro predictions: US-align on C1′, TM normalised by the experimental structure; prediction 1 and
  best of 5. Differences: paired bootstrap over chains, 2,000 resamples, 95% interval.

## 1. Each search method on its own (date filter)

| Method | Train OOF best TM@1 | best TM@5 | hit@5 | Validation best TM@1 | best TM@5 | hit@5 |
|---|---|---|---|---|---|---|
| Two-tower (our learned retriever) | 0.320 | 0.367 | 0.493 | 0.311 | 0.363 | 0.547 |
| MMseqs2 (sensitive) | 0.260 | 0.284 | 0.663 | 0.273 | 0.311 | 0.693 |
| 3-mer similarity | 0.309 | 0.385 | 0.586 | 0.283 | 0.371 | 0.587 |
| First-place Kaggle search (john) | 0.369 | 0.423 | 0.769 | 0.356 | 0.417 | 0.760 |
| Method 1 | 0.379 | 0.433 | 0.765 | 0.362 | 0.422 | 0.760 |
| Method 2 | 0.377 | 0.433 | 0.764 | 0.371 | 0.421 | 0.747 |
| Method 3 (embedding similarity) | 0.292 | 0.367 | 0.551 | 0.278 | 0.353 | 0.573 |
| Method 4 | 0.382 | 0.430 | 0.751 | 0.360 | 0.421 | 0.747 |
| Method 5 | 0.363 | 0.415 | 0.731 | 0.332 | 0.396 | 0.653 |
| RiboSeek (our re-implementation) | 0.342 | 0.392 | 0.605 | 0.339 | 0.394 | 0.707 |
| *Best template in the library (upper bound)* | *0.494* | *0.494* | *1.000* | *0.488* | *0.488* | *1.000* |

MMseqs2 and Method 5 only return hits; chains with no hit count as TM 0, which lowers their mean.
Without the date filter (train OOF, best TM@5): two-tower 0.378, MMseqs2 0.387, 3-mer 0.418,
john 0.473, Method 1 0.482, Method 2 0.479, Method 3 0.398, Method 4 0.479, Method 5 0.462,
RiboSeek 0.413; upper bound 0.553.

## 2. Chains where only that method found a good template

Pool = top 10 of every method. Count = train chains (1,549) where the pool's best template is a good
one (TM ≥ 0.45) and only this method pooled it (or one within 0.01 TM). Baseline: a "random method"
that adds 10 random templates per chain, run with 20 seeds.

| Method | No date filter | Date filter |
|---|---|---|
| RiboSeek | 56 | 36 |
| Two-tower | 41 | 27 |
| Method 3 (embedding similarity) | 19 | 12 |
| First-place Kaggle search (john) | 18 | 12 |
| 3-mer similarity | 17 | 9 |
| MMseqs2 | 10 | 3 |
| Method 5 | 8 | 7 |
| Method 2 | 5 | 4 |
| Method 4 | 2 | 0 |
| Method 1 | 0 | 0 |
| *Random method, mean over 20 seeds* | *4.85* | *5.65* |
| *Random method, maximum over 20 seeds* | *9* | *11* |

Four methods beat the random maximum in both settings (RiboSeek, two-tower, Method 3, john).
Decision: all ten methods are kept in the pool.

## 3. Learned selector (LambdaRank, all ten methods, date filter)

Pool: about 49 candidates per chain (train), 53 (validation).

| | Train OOF best TM@1 | best TM@5 | hit@1 | hit@5 | Validation best TM@1 | best TM@5 | hit@1 | hit@5 |
|---|---|---|---|---|---|---|---|---|
| First-place Kaggle search (john) | 0.369 | 0.423 | 0.694 | 0.769 | 0.356 | 0.417 | 0.533 | 0.760 |
| **Learned selector** | **0.410** | **0.449** | **0.709** | **0.822** | **0.408** | **0.440** | **0.733** | **0.800** |
| Perfect selector on the pool | 0.479 | 0.479 | 0.917 | 0.917 | 0.471 | 0.471 | 0.920 | 0.920 |

Selector minus john (95% interval; chains better / same / worse):

| | best TM@1 | best TM@5 |
|---|---|---|
| Train OOF | +0.041 [+0.037, +0.046]; 864 / 440 / 245 | +0.025 [+0.022, +0.029]; 721 / 637 / 191 |
| Validation | +0.052 [+0.032, +0.070]; 84 / 49 / 26 | +0.023 [+0.011, +0.034]; 88 / 59 / 12 |

Without the date filter: selector 0.462 / 0.499 (train OOF TM@1 / TM@5), 0.431 / 0.467 (validation);
john 0.419 / 0.473 and 0.393 / 0.446. Training tweaks and ensembles (7 models, 5 ensembles) changed
the selector by at most 0.003 TM, so the plain LambdaRank model is kept.

## 4. RNAPro (released checkpoint `RNAPro-Private-Best-500M`, not retrained)

Validation chains with a usable MSA (123 of 159), date filter, top 5 templates per chain, templates
mapped onto the query by sequence alignment only. 5 predictions per chain, 200 diffusion steps,
10 recycles, fp32 on 2× T4.

| Templates | Templates alone, first | Templates alone, best of 5 | RNAPro prediction 1 | RNAPro best of 5 | Chains with best TM ≥ 0.45 |
|---|---|---|---|---|---|
| First-place Kaggle search (john) | 0.351 | 0.412 | 0.705 | 0.747 | 88.6% |
| Learned selector | 0.377 | 0.422 | 0.708 | 0.746 | 88.6% |
| **Selector minus john** | **+0.026 [+0.002, +0.050]** | +0.011 [−0.010, +0.033] | +0.003 [−0.012, +0.018] | −0.001 [−0.008, +0.007] | — |

(Chains better / same / worse for RNAPro prediction 1: 31 / 63 / 29.)

First run, 50 of these chains, templates adapted as in john's notebook (refinement + noise):
RNAPro + john 0.665 / 0.716 (prediction 1 / best of 5), RNAPro + selector 0.685 / 0.719;
difference +0.020 [−0.011, +0.060] / +0.003 [−0.004, +0.010]. The lead did not hold on the other
73 chains.

Published RNAPro, for reference only (different targets): 0.640 (paper text) / 0.648 (Table 2).

**Control, each chain's own experimental structure given as the template** (first 50 chains):
RNAPro reaches 0.812 (prediction 1) / 0.812 (best of 5), against 0.670 / 0.710 with john's plain
templates: +0.142 [+0.100, +0.189] at prediction 1, 45 of 50 chains better. So RNAPro does use
templates, but only a near-perfect template moves it much; templates of the quality any search finds
here (TM about 0.35–0.42) do not.

**In one line:** the selector picks significantly better templates than the first-place search, but
RNAPro's final structures are the same with either set on these (mostly template-rich) validation
chains; RNAPro gains clearly only from near-perfect templates (+0.14 TM with the true structure).

## 5. Test set (176 chains, scored once; selector trained on the 1,549 train chains)

70 of the 176 test chains have a good template (TM ≥ 0.45) in the library under the date filter
(90 without it); hit@k is counted over those.

**Selector, date filter:**

| | best TM@1 | best TM@5 | hit@1 | hit@5 |
|---|---|---|---|---|
| First-place Kaggle search (john) | 0.351 | 0.398 | 0.686 | 0.757 |
| **Learned selector** | **0.395** | **0.425** | **0.743** | **0.814** |
| Perfect selector on the pool | 0.453 | 0.453 | 0.929 | 0.929 |
| Best template in the library | 0.468 | 0.468 | 1.000 | 1.000 |
| **Selector minus john** | **+0.043 [+0.031, +0.056]** | **+0.026 [+0.017, +0.036]** | +0.057 | +0.057 |

Chains better / same / worse than john: 104 / 43 / 29 (TM@1), 90 / 64 / 22 (TM@5).
Without the date filter: selector 0.419 / 0.457, john 0.392 / 0.436 (TM@1 / TM@5), difference
+0.027 [+0.011, +0.044] / +0.021 [+0.011, +0.032].

**Each method alone on test, date filter (best TM@1 / best TM@5 / hit@5):** two-tower 0.318 / 0.375 /
0.614; MMseqs2 0.215 / 0.234 / 0.600; 3-mer 0.287 / 0.355 / 0.529; john 0.351 / 0.398 / 0.757;
Method 1 0.360 / 0.406 / 0.771; Method 2 0.358 / 0.407 / 0.771; Method 3 0.292 / 0.362 / 0.586;
Method 4 0.360 / 0.408 / 0.786; Method 5 0.344 / 0.391 / 0.771; RiboSeek 0.332 / 0.387 / 0.686.

**Test chains where only that method found a good template (no filter / date filter):** two-tower
9 / 10, RiboSeek 2 / 6, 3-mer 1 / 1, Method 3 1 / 1, Method 4 1 / 0, Method 2 1 / 0, Method 1 0 / 1,
MMseqs2 0 / 0, john 0 / 0, Method 5 0 / 0.

**RNAPro on test** (141 of the 176 test chains have a usable MSA; lengths 20–470, median 69; plain
templates, date filter; no chain failed):

| Templates | Templates alone, first | Templates alone, best of 5 | RNAPro prediction 1 | RNAPro best of 5 | Chains with best TM ≥ 0.45 |
|---|---|---|---|---|---|
| First-place Kaggle search (john) | 0.365 | 0.408 | 0.724 | 0.764 | 86.5% |
| Learned selector | 0.375 | 0.415 | 0.719 | 0.758 | 85.8% |
| **Selector minus john** | +0.010 [−0.009, +0.027] | +0.007 [−0.003, +0.018] | −0.005 [−0.027, +0.018] | **−0.006 [−0.012, −0.001]** | — |

(Chains better / same / worse for RNAPro: 34 / 62 / 45 at prediction 1, 26 / 74 / 41 at best of 5.)
On test, RNAPro with the selector's templates is the same as with john's at prediction 1 and
slightly worse at best of 5 (−0.006, interval just below zero).

## Not done (do not report as results)

RNA3DB / family-held-out benchmark; template-poor chains reported
separately; C1′ RMSD; per-target Z-scores.
