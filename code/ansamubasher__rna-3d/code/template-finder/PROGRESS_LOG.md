# Two-tower template retriever and selector: progress log

Everything done so far, in order. For each step: what was done, what changed, and what the
result meant for the next step. All runs are private Kaggle notebooks under `alizehadeel/`;
the script for each is in `methods/`, `selector/`, `data/` or `rnapro/` (`<group>/<folder>/`). The test split was used once, in Step 33.

Last updated: 2026-11-18.

## Terms used below

| Term | Meaning |
|---|---|
| Query | The RNA chain whose structure we want to predict (only its sequence is used) |
| Template | A chain with a known structure that might resemble the query |
| TM-score | Structural similarity from US-align, 0 to 1, normalised by the query length. 0.45 or more counts as "similar" |
| hit@k | Share of queries (among those that have a similar template) with a similar template in the top k |
| best TM@k | Mean over all queries of the best TM-score in the top k |
| Spearman | How well a method orders the whole template list, per query |
| Date filter | Only templates released before the query are allowed |

Data: 1,884 chains (1,549 train, 159 validation, 176 test), split by sequence family.
Validation queries are always searched against the 1,549 train structures.

---

## Step 0. Structural similarity labels (US-align)

- **Notebooks:** `usalign-timing`, `usalign-labels`
- **Done:** ran US-align on every pair of chains to get TM-scores and residue alignments.
- **Result:** 1,773,786 pairs. 3.2% are similar (TM 0.45 or more). 92% of the similar pairs in
  train are between different sequence families.
- **Interpretation:** similar structure often occurs without similar sequence, so a retriever
  that looks beyond sequence has something to find.

## Step 1. Label check and split files

- **Notebook:** `label-check`
- **Done:** verified the labels and wrote pair tables per split (`pairs_train/val/test.parquet`).
- **Result:** all hard checks passed. 92 of 159 validation queries have a similar train
  template (75 with the date filter); 90 of 176 test queries (70 dated). 310 train chains have
  no similar partner.
- **Interpretation:** only 58% of validation queries can be helped by any retriever. The mean
  best TM-score possible is 0.533; that is the ceiling for every method below.

## Step 2. Model inputs

- **Notebook:** `build-features`
- **Done:** one file with sequences, backbone coordinates (P, C4', C1', C3', N) and the maps
  between sequence positions, structure residues and US-align residues.
- **Result:** US-align lengths reproduced for all 1,884 chains; RMSD recomputed from our maps
  matched US-align within 0.005 A on 3,000 pairs.
- **Interpretation:** inputs and index maps are correct, so training can start.

## Step 3. Build and train the two towers

- **Notebook:** `train-towers` (GPU, 2 h 45 min)
- **Done:** sequence tower (Transformer) and structure tower (GVP-style geometric network),
  both from scratch. Score = cosine of the two vectors, trained to match the TM-score.
  Two objectives trained separately: regression and contrastive.
- **Result on validation:**

| Method | hit@1 | hit@5 | hit@10 | best TM@1 | best TM@5 | Spearman |
|---|---|---|---|---|---|---|
| Random order | 0.08 | 0.22 | 0.34 | 0.213 | 0.292 | 0.00 |
| Closest length | 0.26 | 0.41 | 0.46 | 0.270 | 0.338 | 0.15 |
| 3-mer sequence similarity | 0.34 | 0.53 | 0.58 | 0.296 | 0.375 | 0.39 |
| Two-tower, regression | 0.42 | 0.44 | 0.47 | 0.341 | 0.374 | 0.65 |
| Two-tower, contrastive | 0.45 | 0.49 | 0.53 | 0.307 | 0.366 | 0.29 |

- **Interpretation:** the two-tower beats simple 3-mer similarity at rank 1 but not at ranks
  5 to 10. Validation stops improving around pass 45 while training keeps improving, so the
  model does not generalise further to unseen families. Regression is the better objective.

## Step 4. Tuning

- **Notebook:** `tune-towers` (GPU, 2 h 34 min)
- **Changed:** combined loss, stronger regularisation, a smaller model, and a variant where the
  template vector also uses the template's sequence. Five variants, 60 passes each.
- **Result:** no variant clearly better (best TM@5 between 0.369 and 0.381). Adding the 3-mer
  score to the model's score helped a little (hit@10 0.54 to 0.64 for one variant).
- **Interpretation:** tuning inside this design is exhausted. The model and 3-mer similarity
  find different templates.

## Step 5. Richer inputs: MSA features

- **Notebooks:** `msa-depth`, `build-msa-features` (CPU), `train-msa` (GPU, 1 h 45 min)
- **Changed:** gave the sequence tower a per-position MSA profile, and then pairwise
  covariation as an attention bias. Three variants: sequence only, + profile, + profile and
  covariation.
- **Checks first:** 1,443 chains have an alignment; 54% of chains have a deep one. The top
  co-varying pairs are close in 3D 51% to 68% of the time (background 5% to 11%), so the
  features carry real signal.
- **Result:** best TM@5 0.375 / 0.377 / 0.372 for the three variants. No gain, also not for
  queries with deep alignments. Spearman rose slightly (0.61 to 0.63), within noise.
- **Interpretation:** the query's inputs are not the bottleneck. The limit is generalising to
  new families from about 1,500 chains. The model is weakest on short, shallow-alignment
  queries.
- **Problem met:** the first run died from memory (a compressed array was re-read in a loop);
  fixed and re-run.

## Step 6. Change of plan: several methods plus a selector

- **Decision:** the two-tower does not have to win alone. Several template-finding methods
  each propose candidates, and a learned selector chooses among them. Methods that find
  different templates are an advantage.
- **Selector defined as:** pool the top candidates of every method, score each
  (query, candidate) pair from what the methods say about it, keep the best.
- **Rules set:** every trained method must score the selector's queries without having trained
  on them; the selector is cross-validated by family; the test split is used once at the end.

## Step 7. RNAPro paper review

- **Done:** read the paper (bioRxiv 2025.12.30.696949) for baselines and dataset.
- **Baselines found (mean TM-align on the paper's 20 hidden targets):** MMseqs2 0.321,
  john's template-only pipeline 0.591, best existing template 0.679, RNAPro 0.648.
- **Dataset:** same Kaggle source as ours. Ours is a filtered subset (length 20 to 512, at
  least 80% resolved, duplicates removed), with a template pool of 1,549 chains instead of the
  whole PDB, and a family split instead of a date split. None of our chains is dated after
  2025-05-29, so nothing overlaps the paper's test targets.
- **Interpretation:** the paper's numbers cannot be compared with ours directly (hidden
  targets, different metric). The baselines have to be re-run on our queries. The paper also
  says only 3 of 12 CASP15 targets have a usable template, so CASP15 is a weak benchmark for
  template finding.

## Step 8. MMseqs2 baseline

- **Notebook:** `mmseqs-baseline` (CPU)
- **Done:** the paper notebook's MMseqs2 search on our chains, plus a more sensitive setting
  (shorter k-mers, maximum sensitivity; our addition).
- **Result on validation:**

| Method | hit@1 | hit@5 | hit@10 | best TM@5 | Spearman |
|---|---|---|---|---|---|
| MMseqs2, paper settings | 0.34 | 0.45 | 0.49 | 0.358 | 0.07 |
| Two-tower | 0.41 | 0.47 | 0.47 | 0.375 | 0.61 |
| MMseqs2, sensitive | 0.51 | 0.69 | 0.72 | 0.433 | 0.11 |
| Two-tower + MMseqs2 sensitive, scores added | 0.52 | 0.71 | 0.75 | 0.444 | 0.61 |

- **Interpretation:** with paper settings MMseqs2 returns a hit for only 57 of 159 queries, so
  the two-tower beats it. The sensitive setting is the best single method so far. Pooling the
  top 5 of the two-tower and MMseqs2 raises the share of queries with a similar candidate from
  0.69 to 0.76, so the two-tower finds queries MMseqs2 misses. 3-mer adds almost nothing once
  MMseqs2 is in the pool.
- **Also produced:** `method_scores.npz`, every method's score table in one common format.

## Step 9. First selector

- **Notebook:** `selector-v1` (CPU)
- **Done:** pooled the top 10 of two-tower, MMseqs2 sensitive and 3-mer (about 29 candidates
  per query); 22 features per candidate; ridge regression and small boosted trees; 5-fold
  cross-validation by family, repeated 5 times.
- **Result on validation:**

| Method | hit@1 | hit@5 | hit@10 | best TM@1 | best TM@5 |
|---|---|---|---|---|---|
| Best rule (scores added) | 0.54 | 0.70 | 0.75 | 0.382 | 0.446 |
| Selector, boosted trees | 0.61 | 0.71 | 0.72 | 0.401 | 0.449 |
| Perfect selector on the pool | 0.80 | 0.80 | 0.80 | 0.482 | 0.482 |
| Best possible, any template | | | | 0.533 | 0.533 |

- **Interpretation:** the selector picks a better first template (best TM@1 +0.019, 95%
  interval +0.008 to +0.031) and ties with the simple rule at top 5 and 10. Its strongest
  input is the two-tower score, so the two-tower is most useful as a judge of candidates
  rather than as a finder. The remaining gap has two parts: selector to pool ceiling
  (0.449 to 0.482), and pool ceiling to best possible (0.482 to 0.533), which only new methods
  can close.

## Step 10. john's template search

- **Notebook:** `john-search` (CPU, under a minute of alignment)
- **Done:** re-implemented the template search of the competition winner, which RNAPro uses to
  pick its five templates. Score = 0.4 global alignment + 0.3 local alignment + 0.2 composition
  similarity + 0.1 shared 3-mers, after a length filter; the final five are picked for
  diversity. Alignments use parasail; checked against the notebook's Biopython scores on 200
  pairs (difference 0.0).
- **Result on validation:**

| Method | hit@1 | hit@5 | hit@10 | best TM@1 | best TM@5 | Spearman |
|---|---|---|---|---|---|---|
| Two-tower | 0.41 | 0.47 | 0.47 | 0.337 | 0.375 | 0.61 |
| MMseqs2, sensitive | 0.51 | 0.69 | 0.72 | 0.368 | 0.433 | 0.11 |
| john, ranked by score | 0.58 | 0.76 | 0.80 | 0.393 | 0.446 | 0.19 |
| john, his final five | 0.58 | 0.76 | | 0.393 | 0.457 | |

- **Interpretation:** john's search is the strongest single method and is the baseline to beat
  (best TM@5 0.457). It also adds templates the others miss: pooling the top 5 of each method
  goes from 0.77 to 0.83 of queries with a similar candidate when john is added.

## Step 11. Selector with four methods

- **Notebook:** `selector-v1` version 2 (CPU)
- **Changed:** john's score added as a fourth method; pool is now about 36 candidates per query
  and 27 features. Nothing else changed.
- **Result on validation:**

| Method | hit@1 | hit@5 | hit@10 | best TM@1 | best TM@5 | best TM@10 |
|---|---|---|---|---|---|---|
| john alone | 0.58 | 0.76 | 0.80 | 0.393 | 0.446 | 0.464 |
| Best rule (rank fusion of all methods) | 0.64 | 0.72 | 0.76 | 0.393 | 0.448 | 0.461 |
| Selector, ridge | 0.62 | 0.74 | 0.76 | 0.383 | 0.444 | 0.461 |
| Selector, boosted trees | 0.69 | 0.74 | 0.77 | 0.412 | 0.461 | 0.473 |
| Perfect selector on the pool | 0.88 | 0.88 | 0.88 | 0.499 | 0.499 | 0.499 |
| Best possible, any template | | | | 0.533 | 0.533 | 0.533 |

- **Interpretation:** the boosted-trees selector now beats the best rule at every cut-off
  (best TM@1 +0.019, @5 +0.013, @10 +0.012; all three 95% intervals exclude zero). With the
  date filter it beats john alone at top 1 (+0.022, interval excludes zero) and is ahead but
  not clearly at top 5 (+0.008). The ridge selector does not beat the rules, so the gain comes
  from interactions between methods. The two-tower score is still the selector's strongest
  input. The pool ceiling rose from 0.482 to 0.499.

## Step 12. 5-fold two-tower (out-of-fold scores)

- **Notebook:** `crossfit-towers` (GPU T4, about 2.3 hours)
- **Changed:** the 1,549 train chains were cut into 5 folds with whole families together
  (786 families, largest 41 chains, folds of 310/310/310/310/309). Five models each train on
  4 folds and score the fold they never saw, against templates from the other four folds only.
  A sixth model trains on all train chains and scores validation and test queries. Every model
  runs a fixed 50 passes and the last state is used; no checkpoint is picked on validation.
  Output `twotower_oof.npz` holds the honest scores for all chains.
- **Result:**

| Queries | Method | hit@1 | hit@5 | hit@10 | best TM@1 | best TM@5 | best TM@10 | Spearman |
|---|---|---|---|---|---|---|---|---|
| 1,549 train, out-of-fold (947 with a similar template) | two-tower | 0.34 | 0.39 | 0.43 | 0.334 | 0.378 | 0.394 | 0.58 |
| same | 3-mer similarity | 0.37 | 0.55 | 0.62 | 0.335 | 0.418 | 0.445 | 0.38 |
| 159 validation | two-tower, full model, last state | 0.41 | 0.46 | 0.46 | 0.328 | 0.374 | 0.384 | 0.60 |
| 159 validation, date filter | same | 0.52 | 0.55 | 0.55 | 0.311 | 0.363 | 0.374 | 0.58 |

  Per fold, best TM@5 ranged from 0.356 to 0.393 and Spearman from 0.574 to 0.584. Best
  possible best TM on the out-of-fold queries is 0.553.

- **Interpretation:**
  - Picking the checkpoint on validation had barely flattered the earlier numbers: validation
    best TM@5 is 0.374 without selection against 0.375 with it, and Spearman 0.60 against 0.61.
  - On ten times as many queries the picture from validation holds. The two-tower orders all
    templates much better than 3-mer similarity (Spearman 0.58 against 0.38) but is worse at
    putting a similar template in the top 5 or 10 (hit@5 0.39 against 0.55). At top 1 the two
    are level on best TM.
  - The two-tower is not a good method on its own. Its value is as an input to the selector.
  - There are now honest two-tower scores for 1,549 + 159 = 1,708 queries, so the selector can
    be trained on about ten times more queries than before.

## Step 13. Selector v2: trained on the train queries

- **Notebook:** `selector-v2` (CPU, under a minute)
- **Changed:** the selector no longer learns from the validation queries. Every train chain is a
  training query, with candidates from the other four folds only and the out-of-fold two-tower
  scores from Step 12. Same pool (top 10 of each of the four methods), same 27 features, same
  ridge and boosted-trees settings as before, plus one larger tree model (depth 5, 400 trees).
  Two evaluations: (A) train on all 1,549 train queries, test on the 159 validation queries;
  (B) 5-fold cross-validation inside the train queries with the two-tower's family folds.
- **Result, no date filter:**

| Queries | Method | hit@1 | hit@5 | hit@10 | best TM@1 | best TM@5 | best TM@10 |
|---|---|---|---|---|---|---|---|
| A: 159 validation | john alone | 0.58 | 0.76 | 0.80 | 0.393 | 0.446 | 0.464 |
| | Rank fusion of all methods | 0.63 | 0.72 | 0.75 | 0.401 | 0.445 | 0.461 |
| | Selector, ridge | 0.66 | 0.74 | 0.77 | 0.396 | 0.443 | 0.461 |
| | Selector, boosted trees | 0.66 | 0.74 | 0.79 | 0.410 | 0.458 | 0.478 |
| | Selector, boosted trees, larger | 0.68 | 0.79 | 0.82 | 0.426 | 0.469 | 0.483 |
| | Perfect selector on the pool | 0.88 | 0.88 | 0.88 | 0.497 | 0.497 | 0.497 |
| B: 1,549 train, out-of-fold | john alone | 0.69 | 0.76 | 0.78 | 0.419 | 0.473 | 0.487 |
| | Rank fusion of all methods | 0.65 | 0.76 | 0.80 | 0.418 | 0.475 | 0.493 |
| | Selector, ridge | 0.67 | 0.74 | 0.78 | 0.426 | 0.474 | 0.491 |
| | Selector, boosted trees | 0.71 | 0.78 | 0.81 | 0.439 | 0.488 | 0.501 |
| | Selector, boosted trees, larger | 0.71 | 0.79 | 0.81 | 0.442 | 0.490 | 0.502 |
| | Perfect selector on the pool | 0.87 | 0.87 | 0.87 | 0.518 | 0.518 | 0.518 |

- **Gain of the larger tree selector over john alone (best TM, 95% interval):**

| Queries | Date filter | top 1 | top 5 | top 10 |
|---|---|---|---|---|
| A: validation | no | +0.033 (+0.019 to +0.048) | +0.023 (+0.015 to +0.031) | +0.019 (+0.011 to +0.027) |
| A: validation | yes | +0.042 (+0.028 to +0.058) | +0.019 (+0.013 to +0.025) | +0.018 (+0.010 to +0.024) |
| B: train, out-of-fold | no | +0.023 (+0.018 to +0.028) | +0.017 (+0.013 to +0.021) | +0.015 (+0.011 to +0.019) |
| B: train, out-of-fold | yes | +0.025 (+0.020 to +0.029) | +0.016 (+0.012 to +0.020) | +0.014 (+0.011 to +0.018) |

- **Interpretation:**
  - The selector beats john's search, the strongest single method, at every cut-off, with and
    without the date filter, on both query sets. Every interval excludes zero. In Step 11 the
    top-5 gain under the date filter was not clear; it now is.
  - On 1,549 queries the gain is about +0.02 best TM at top 1 and +0.016 at top 5. It is real
    but small: the selector closes roughly a quarter of the gap between john and the perfect
    selector on the pool (0.473 to 0.490 of a possible 0.518 at top 5).
  - The larger tree model is the one to keep. Evaluation B, which does not touch validation,
    puts it level with or slightly ahead of the smaller one, and validation agrees.
  - The ridge selector again does not beat the rules, so the gain comes from interactions
    between methods, not from a weighted sum.
  - The two-tower score is still the single input most correlated with TM (0.67), although the
    two-tower is the weakest method on its own.
  - The remaining headroom is mostly outside the selector: best possible is 0.553 against a
    pool ceiling of 0.518, and 13% of queries with a similar template have none in the pool.
    New methods that find those templates would raise the ceiling.

## Step 14. Selector v3: room for the team's other template-finding methods

- **Notebook:** `selector-v3` (CPU, about a minute per method set)
- **Changed:** the selector code is the same as v2, with three additions so new methods can be
  added one at a time:
  - any input `method_scores_<name>.npz` (chain order of `chains.tsv`, a full 1,884 × 1,884
    score matrix called `<name>`, higher = better) is picked up as an extra method;
  - several method sets run in one go (`SV_CONFIGS`); by default `base` (the four methods of v2)
    and `base` plus each extra method. Each set's larger tree selector is compared with `base` on
    the same queries (paired bootstrap), plus the change in pool ceiling and pool size
    (`selector3_config_compare.csv`);
  - optional hit-only pooling (`SV_SPARSE`): for methods where 0 means "no hit", non-hits are no
    longer pooled as 10 random templates. Off by default.
- **Result:** with no extra method, all 44 numbers of `selector2_summary.csv` are reproduced
  exactly (largest difference 0.0). The new code changes nothing when no method is added.
- **Next:** Method 3 (RibonanzaNet2 embeddings, from `all_methods.zip`), Step 15.

## Step 15. Method 3 (RibonanzaNet2 embeddings) added to the selector

- **Notebooks:** `method3-embed` (T4 GPU, 19 minutes), then `selector-v3` version 2 (CPU)
- **Done:** the teammate's embeddings file was not available, so `method3-embed` recomputed it:
  RibonanzaNet2 (Kaggle model `shujun717/ribonanzanet2`, the weights RNAPro uses) with RNAPro's own
  `ribonanzanet.py`, loaded with strict weights; tokens A0 C1 G2 U3; one chain at a time. The
  final layer's residue features are averaged per chain (all 48 layer means are saved too, in
  `ribonanzanet2_layer_means.npz`). On a test chain the layer loop equals RNAPro's
  `get_embeddings` exactly. Scores: the "standardised" variant Method 3 chose (statistics from the
  train chains), cosine for every pair, as method `emb`.
- **Check against Method 3's numbers:** nearest neighbour in the same team family, 50.7% plain and
  74.2% standardised here, against 50.6% and 73.6% in Method 3's notebook (which also excluded the
  same PDB entry). The recomputed embeddings behave like the originals.
- **Result (larger tree selector; `base+emb` minus `base`, same queries, 95% interval):**

| Queries | Date filter | Pool size per query | Pool ceiling | Selector best TM@1 | Selector best TM@5 |
|---|---|---|---|---|---|
| A: 159 validation | no | 35.4 → 43.7 | +0.001 (−0.001 to +0.003) | −0.002 (−0.012 to +0.007) | −0.002 (−0.010 to +0.005) |
| A: 159 validation | yes | 34.3 → 42.1 | +0.001 (−0.001 to +0.003) | −0.007 (−0.014 to +0.000) | +0.001 (−0.002 to +0.004) |
| B: 1,549 train, out-of-fold | no | 35.2 → 43.3 | +0.003 (+0.002 to +0.004) | +0.002 (−0.002 to +0.005) | +0.001 (−0.001 to +0.003) |
| B: 1,549 train, out-of-fold | yes | 33.3 → 40.3 | +0.002 (+0.002 to +0.003) | +0.002 (−0.001 to +0.004) | −0.001 (−0.002 to +0.001) |

  Method 3 alone (evaluation B, no filter): best TM@1 0.319, @5 0.398, against john 0.419 / 0.473.

- **Interpretation:**
  - Method 3 adds about 8 new candidates per query to the pool, but they are rarely better than
    what is already there: the pool ceiling rises by only 0.003 (69 of 1,549 queries gain, none
    lose).
  - The selector does not improve: every interval for TM@1 and TM@5 includes zero. The embedding
    features get near-zero weights (correlation with TM 0.04 to 0.11, against 0.67 for the
    two-tower score).
  - This agrees with Method 3's own finding (worse than sequence alignment; 4-mer counts recover
    families better). By the keep rule (the evaluation B top-5 interval must exclude zero),
    Method 3 is **not kept**. The selector stays at `base`.
  - Small side effect: with an extra method the random tie-breaks of methods with many zero scores
    (MMseqs2) change, so the validation pool's hit rate moves by about 0.01 although the pool is
    otherwise a superset. Hit-only pooling (`SV_SPARSE=mmseqs`) would remove this noise.

## Step 16. Method 4 (ViennaRNA secondary structure) added to the selector

- **Notebooks:** `method4-scores` (CPU, under 2 minutes of compute), then `selector-v3` version 3
  (CPU; sets `base`, `base+emb`, `base+m4`, `all`)
- **Done:** Method 4's score for every pair, as method `m4`:
  0.25 × structure score + 0.75 × sequence score, each divided by the query's perfect self-score.
  Both scores are the same end-gap-free alignment (match +2, mismatch −1, gap −2), on the bases
  and on the dot-bracket letters of the ViennaRNA 2.8.0 minimum-free-energy fold. Weight 0.25 is
  the one Method 4 chose on its validation split. The alignment was rewritten in numba so all
  ~1.8 million pairs take 42 s.
- **Checks:** the numba alignment equals Method 4's own code exactly: all 166 × 1,549 saved
  sequence scores (largest difference 0.0) and 300 random structure pairs (0.0). All 1,884 folds
  and energies are identical to Method 4's `vienna_mfe_structures.csv`.
- **Result (larger tree selector; `base+m4` minus `base`, same queries, 95% interval):**

| Queries | Date filter | Pool size per query | Pool ceiling | Selector best TM@1 | Selector best TM@5 |
|---|---|---|---|---|---|
| A: 159 validation | no | 35.4 → 41.3 | +0.004 (−0.000 to +0.009) | −0.005 (−0.019 to +0.006) | −0.003 (−0.014 to +0.006) |
| A: 159 validation | yes | 34.3 → 39.3 | +0.006 (+0.002 to +0.011) | −0.001 (−0.010 to +0.006) | −0.001 (−0.009 to +0.006) |
| B: 1,549 train, out-of-fold | no | 35.2 → 41.0 | +0.004 (+0.003 to +0.006) | +0.000 (−0.003 to +0.003) | **+0.003 (+0.001 to +0.005)** |
| B: 1,549 train, out-of-fold | yes | 33.3 → 37.9 | +0.004 (+0.003 to +0.005) | +0.004 (+0.000 to +0.008) | **+0.004 (+0.002 to +0.006)** |

  Method 4 alone (evaluation B, no filter): best TM@1 0.429, @5 0.479, against john 0.419 / 0.473.
  Adding Method 3 as well (`all`) gives no further selector gain over `base+m4` (+0.002 and +0.004
  at TM@5 against `base`, the same as `base+m4`).

- **Interpretation:**
  - Method 4 is the strongest single method so far, slightly ahead of john's search, which makes
    sense: 75% of it is a full sequence alignment of every pair.
  - It passes the keep rule: the evaluation B top-5 interval excludes zero with and without the date
    filter. The gain is small (+0.003 to +0.004 best TM@5), and validation (159 queries, intervals
    about ten times wider) does not confirm it; its point estimates are slightly negative.
  - The pool ceiling rises by 0.004 (127 of 1,549 queries gain, none lose), more than Method 3 gave.
  - Its z-score is the second most useful kind of feature after the two-tower (correlation with TM
    0.45).
  - **Decision: Method 4 is kept**; the selector's method set is now `base+m4`. Method 3 stays out.

## Step 17. Method 1 (Rfam families, Infernal) added to the selector

- **Notebooks:** `method1-rfam` (CPU: Infernal 1.1.5 built from source, Rfam 15.1 downloaded,
  `cmscan` over all chains in 7 minutes), then `selector-v3` version 4 (sets `kept` = base + m4,
  `kept+m1`, and `base` for reference; `kept` is the reference)
- **Done:** every chain labelled with Method 1's exact settings
  (`cmscan --cut_ga --rfam --nohmmonly --fmt 2 --clanin`, `-Z` = 2 × total length ÷ 10⁶ = 0.347;
  overlapping `=` and minus-strand hits dropped). Method 1's "Rfam + fallback" ranking (same Rfam
  family first, then the rest, both by sequence alignment score) written as one score per pair:
  `m1 = shares an Rfam family + sequence score ÷ query's perfect self-score`. Sequence scores are
  those of `method4-scores`.
- **Checks:** the labels match Method 1's run: 855 of 1,884 chains labelled (45.4%), 4,227 Rfam
  families, and the same top families (tRNA 275, 5S rRNA 92, 5.8S rRNA 37, SAM 24). So Method 1
  most likely used Rfam 15.1 too. On Method 1's 166 test queries, the `m1` score gives exactly the
  same top 5 as Method 1's own `retrieve_rfam(..., fallback=True)` (0 of 166 differ, checked locally
  with made-up family labels, since cmscan does not run on Windows).
- **Result (larger tree selector; `kept+m1` minus `kept`, same queries, 95% interval):**

| Queries | Date filter | Pool size per query | Pool ceiling | Selector best TM@1 | Selector best TM@5 |
|---|---|---|---|---|---|
| A: 159 validation | no | 41.3 → 44.2 | +0.005 (+0.002 to +0.010) | +0.005 (−0.004 to +0.014) | +0.003 (−0.001 to +0.007) |
| A: 159 validation | yes | 39.3 → 41.4 | +0.002 (−0.000 to +0.004) | −0.008 (−0.020 to +0.003) | −0.000 (−0.009 to +0.006) |
| B: 1,549 train, out-of-fold | no | 41.0 → 43.9 | +0.001 (+0.001 to +0.002) | +0.005 (+0.001 to +0.009) | +0.001 (−0.001 to +0.004) |
| B: 1,549 train, out-of-fold | yes | 37.9 → 39.9 | +0.001 (+0.001 to +0.002) | +0.001 (−0.003 to +0.004) | +0.000 (−0.002 to +0.002) |

  Method 1 alone (evaluation B, no filter): best TM@1 0.427, @5 0.481 (john 0.419 / 0.473,
  Method 4 0.429 / 0.479).

- **Interpretation:**
  - Method 1 alone is about as good as Method 4 and slightly better than john; like Method 4, most
    of its ranking is sequence alignment.
  - Its score is the feature most correlated with TM of all (0.80), because "same Rfam family" is a
    strong signal where it applies. But the selector already gets that signal from the other
    methods: the pool gains a better template for only 40 of 1,549 queries.
  - By the keep rule (evaluation B top-5 interval must exclude zero) Method 1 is **not kept**: the
    TM@5 intervals include zero with and without the date filter. There is a significant TM@1 gain
    without the date filter (+0.005), but it disappears with the filter, and TM@1 is not the rule.
  - **Decision:** the selector's method set stays `base+m4` (Step 16).

---

## Step 18. RNAPro set up and run with john's templates (50 validation chains)

- **Notebooks:** `rnapro-inputs` (CPU), `rnapro-run` (GPU, 2× T4), `rnapro-score` (CPU).
- **Inputs:** 50 validation chains with a competition MSA (123 of 159 have one), shuffled with
  seed 0, 20–369 nt (median 70). Templates: john's top 5, date filter on (only templates released
  before the query), mapped onto the query with john's own alignment code, in competition
  submission format.
- **Model:** RNAPro code at commit `83a0b90`, weights `nvidia/RNAPro-Private-Best-500M`,
  RibonanzaNet2 from Kaggle. Inference only. On T4: fp32, plain-torch attention kernels,
  10 recycles, 200 diffusion steps, one prediction per template (5 per chain).
- **Scoring:** US-align on C1′, TM normalised by the true structure; prediction 1 and best of 5.
- **Run:** all 50 chains, no errors; about 85 min inference + 7 min setup (≈3 GPU hours);
  peak GPU memory 13.1 of 15 GB (369-nt chain).
- **Result (same 50 chains):**

| Source | TM, prediction 1 | TM, best of 5 | Chains with best TM ≥ 0.45 |
|---|---|---|---|
| john's templates alone | 0.311 | 0.351 | 26% |
| RNAPro + john's templates | 0.665 | 0.716 | 84% |

  Gain in best of 5: +0.365 (95% interval 0.306 to 0.419); RNAPro better on 48 of 50 chains.
  By length (best of 5, RNAPro): ≤50 nt 0.73, 50–100 nt 0.75, 100–369 nt 0.65.
- **Caveat:** RNAPro was trained on the Kaggle data, which very likely contains these chains, so
  the absolute scores are optimistic. Use them to compare template sources through the same
  RNAPro, not as RNAPro's true accuracy.
- **Next:** the same 50 chains with the retrained selector's top-5 templates (same format, swap
  the template file with `RR_TEMPLATES` / `RR_TAG`), then a paired comparison.

---

## Step 19. New keep rule for methods, and a selector that is better at picking

- **Notebook:** `selector-v4` (CPU, 5.8 min). Code: `selector/selector_v4/selector_v4.py`.
- **Keep rule changed.** Old rule (Steps 15–17): keep a method if the selector's top-5 best TM
  significantly improves. New rule: keep a method if it **adds better templates to the pool**
  (the pool ceiling, i.e. the best template anywhere in the pool, rises with a 95% interval above
  zero) **and the selector does not get significantly worse** (top-5 interval not entirely below
  zero). Both judged on evaluation B (1,549 train queries, out-of-fold), with and without the date
  filter. Reason: finding templates is the methods' job; picking them is the selector's job.
- **Leave-one-out test:** each method is tested as "all methods" minus "all methods except this
  one", so it must add templates nobody else finds.
- **Other change:** MMseqs2 is now hit-only (its zero-score non-hits are no longer pooled as random
  filler). Before, adding a method shuffled random filler templates in and out of the pool.

- **Part 1 result (evaluation B, top-5 best TM, all methods minus all-but-this-one):**

| Method | Pool ceiling, no filter | Pool ceiling, date filter | Queries with a better template in pool (no filter / date) | Selector top 5, no filter | Selector top 5, date filter | Decision |
|---|---|---|---|---|---|---|
| Method 4 (m4) | +0.002 (+0.001 to +0.003) | +0.001 (+0.001 to +0.002) | 59 / 56 | −0.000 (−0.002 to +0.002) | +0.002 (+0.000 to +0.004) | **kept** |
| Method 1 (m1) | +0.001 (+0.001 to +0.002) | +0.001 (+0.001 to +0.002) | 37 / 41 | −0.000 (−0.003 to +0.002) | +0.001 (−0.001 to +0.003) | **kept** |
| Method 3 (emb) | +0.002 (+0.002 to +0.003) | +0.002 (+0.001 to +0.003) | 52 / 57 | −0.000 (−0.002 to +0.002) | −0.001 (−0.002 to +0.001) | **kept** |

  The method set is now all seven: twotower, mmseqs, kmer3, john, m4, m1, emb.

- **Every method's own contribution** (`selector-v4` version 2, `selector4_method_contribution.csv`;
  1,549 train queries, same pool as the selector; "only source" = without this method the pool's
  best TM drops by more than 0.01; no date filter / date filter):

| Method | Pools the best template (shared or not) | Only source of the best template | ... and that template has TM ≥ 0.45 | Pool best TM lost without it |
|---|---|---|---|---|
| twotower | 355 / 493 | 175 / 143 | 85 / 61 | 0.0045 / 0.0040 |
| mmseqs | 503 / 362 | 21 / 15 | 15 / 6 | 0.0007 / 0.0003 |
| kmer3 | 415 / 501 | 69 / 59 | 24 / 16 | 0.0017 / 0.0017 |
| john | 676 / 646 | 66 / 79 | 34 / 24 | 0.0031 / 0.0031 |
| Method 4 (m4) | 741 / 783 | 53 / 53 | 15 / 6 | 0.0017 / 0.0013 |
| Method 1 (m1) | 721 / 786 | 37 / 41 | 6 / 5 | 0.0013 / 0.0013 |
| Method 3 (emb) | 282 / 365 | 52 / 57 | 26 / 16 | 0.0023 / 0.0020 |

  Every method is the only source of a better template for at least 15 train queries. Twotower
  contributes most on its own (175); mmseqs least (21), since its hits are usually found by
  others too.
  Pool: 46 candidates per query (no filter), 41 (date filter). Caveat: on the 159 validation
  queries (evaluation A, no filter) the selector's top-1 drops when m4 or m1 is added
  (−0.008 and −0.012, intervals just below zero); the selector improvements below more than make up
  for it.

- **Part 2, diagnosis (larger trees, v3 features, all seven methods, evaluation B, no filter):**
  - Selector top-5 best TM 0.494 against a pool ceiling of 0.526.
  - The selector misses the pool's best template by more than 0.05 TM for 337 of 1,549 queries
    (22%). For those, the best template was ranked 6–10 in 81, 11–20 in 121, below 20 in 135. So it
    is rarely a near miss: the selector does not recognise those templates, a features problem more
    than a cut-off problem.
  - For 326 queries (21%) the best template was pooled only by the new methods (m4, m1, emb);
    usually only slightly better than what the original four found (mean 0.05), and the selector
    missed 111 of them by more than 0.05.

- **Part 3, selector variants** (all combinations of 3 changes, compared with the v3-style selector
  on the same queries and the same seven methods):
  - **Diverse picking** (skip a template whose structure has TM ≥ 0.6 with one already picked):
    **worse.** Top-5 best TM −0.007 (−0.009 to −0.005) without filter, −0.005 with; also worse on
    validation. Thresholds 0.4 to 0.8 tried: the looser, the less harm, 0.8 ≈ no change. The best
    templates for a query tend to be near-copies of each other, and picking among near-copies helps
    best-of-5 more than variety. Dropped.
  - **Ranker** (LightGBM LambdaRank, trained per query) instead of regression trees: small gain alone
    (top-5 +0.003 without filter, significant; +0.000 with filter).
  - **New features** (same for every candidate, whichever method found it): sequence identity,
    secondary-structure similarity, same Rfam family, gap to the query's best score per method,
    library fold size, and **structural consensus** (mean template-template TM to the other pooled
    candidates / to the top 5 by rank fusion). Consensus correlates 0.81 with TM, the strongest
    single feature so far (same Rfam family 0.79). Alone with trees: no gain.
  - **Ranker + new features, plain picking: the best, kept.**

| Queries | Date filter | Best TM@1, v3 → v4 | Difference (95% interval) | Best TM@5, v3 → v4 | Difference (95% interval) |
|---|---|---|---|---|---|
| B: 1,549 train, out-of-fold | no | 0.449 → 0.458 | **+0.009 (+0.005 to +0.013)** | 0.494 → 0.497 | **+0.003 (+0.001 to +0.006)** |
| B: 1,549 train, out-of-fold | yes | 0.398 → 0.402 | **+0.004 (+0.000 to +0.008)** | 0.443 → 0.444 | +0.001 (−0.001 to +0.004) |
| A: 159 validation | no | 0.413 → 0.431 | **+0.018 (+0.003 to +0.033)** | 0.465 → 0.470 | +0.005 (−0.003 to +0.011) |
| A: 159 validation | yes | 0.393 → 0.404 | **+0.011 (+0.003 to +0.021)** | 0.435 → 0.440 | **+0.006 (+0.001 to +0.010)** |

  For reference, john alone (B, no filter): 0.419 / 0.473; the pool ceiling: 0.526.
- **Caveat:** 8 variants were compared and the best is reported, so the B numbers for it are
  slightly optimistic; the validation queries (never used for choosing) agree on top 1 with both
  filters.
- **Interpretation:** the gain is mostly at top 1 (+0.004 to +0.018), which matters because RNAPro
  prediction 1 uses template 1. The selector still leaves 0.03 TM in the pool at top 5; most misses
  are templates ranked far down, so better pair features are the place to look next.
- **Next:** use the v4 selector (seven methods, ranker + new features, plain picking) for the
  RNAPro comparison planned in Step 18.

---

## Step 20. Methods 2 and 5 added to the pool (RiboSeek pending)

- **Notebooks:** `method2-scores` (CPU, 0.2 min), `method5-scores` (CPU, 1.1 min), then `selector-v4`
  version 3 (same keep rule as Step 19, now testing m4, m1, emb, m2, m5 leave-one-out).
- **Method 2 (Rfam family lookup):** library chains sharing an Rfam family with the query (Method 1's
  labels), ranked by closeness of length (|log length ratio| in steps of 0.1), then identity, then
  most recent; the rest by sequence alignment ("with fallback"). Written as one score per pair:
  family member `2 + (50 − 10 × length step) + 0.9 × identity + 0.001 × date rank`, otherwise
  `sequence score ÷ (2 × query length)`. **Check:** same top 5, in the same order, as Method 2's
  notebook on all 56 of its test queries with a family template (0 differ).
- **Method 5 (local element search):** the query's ViennaRNA fold is split into elements (each
  outermost base pair closes one; ≥ 15 nt), each element is aligned anywhere inside every library
  chain (0.75 × sequence + 0.25 × structure, Method 4's weights). Written as
  `m5 = best element score over the query's elements`; hit-only (no element = no score).
  2,420 elements in 1,840 of 1,884 chains. **Check:** same top 5 as Method 5's notebook for all 209
  of its test elements (0 differ). Folds are identical to Method 5's for all 1,884 chains.
- **Keep test (leave-one-out, evaluation B, pool best TM, no filter / date filter):**

| Method | Pool gain without filter | Pool gain with filter | Queries improved in pool | Decision |
|---|---|---|---|---|
| Method 4 (m4) | +0.0009 (+0.0003 to +0.0016) | +0.0004 (+0.0002 to +0.0007) | 27 / 20 | kept |
| Method 1 (m1) | +0.0004 (−0.0000 to +0.0011) | +0.0001 (−0.0001 to +0.0003) | 11 / 8 | **not kept** |
| Method 3 (emb) | +0.0023 (+0.0014 to +0.0032) | +0.0020 (+0.0013 to +0.0027) | 55 / 58 | kept |
| Method 2 (m2) | +0.0003 (+0.0001 to +0.0006) | +0.0003 (+0.0001 to +0.0006) | 16 / 14 | kept |
| Method 5 (m5) | +0.0012 (+0.0006 to +0.0020) | +0.0007 (+0.0003 to +0.0012) | 28 / 25 | kept |

  No method makes the selector significantly worse. Method 1 drops out because Method 2 uses the same
  Rfam families and pools nearly the same templates: Method 1 is now the only source of a better
  template (by > 0.01 TM) for just 2 / 3 queries. Dropping it was confirmed by the team (2026-11-18).
  Final set: twotower, mmseqs, kmer3, john, m4, emb, m2, m5. Pool: 49 candidates per query (no filter), 43 (date filter).
- **Only-source counts (train queries, no filter, > 0.01 TM):** twotower 155, john 59, kmer3 57,
  emb 49, m5 28, m4 19, mmseqs 16, m2 13, m1 2.
- **Effect on the selector (ranker + new features, B, no filter):** pool ceiling 0.526 → 0.527;
  selector best TM@1 0.458 → 0.457, TM@5 0.497 → 0.497 — no measurable change. The new templates are
  few and the selector rarely picks them.
- **RiboSeek:** not added yet. The template-search code is not in `riboseek.zip` (only the token model
  and search results), and the token model was trained on the train chains, so its tokens for train
  queries would be optimistic; needs cross-fitting on the 5 family folds (≈1 GPU hour).

---

## Step 21. Selector improvement, step 1: diagnosis of the misses

- **Notebook:** `selector-v5` version 1 (CPU). Code: `selector/selector_v5/selector_v5.py`, the
  harness for all selector improvements from here on (eight methods fixed; reference = the v4
  selector, ranker + new features, plain top 5). Reference numbers reproduce Step 20 exactly.
- **Done:** for every query, the pool's best template against the selector's first pick, with the
  features of both (`selector5_misses.csv`, summary in `selector5_miss_summary.csv`).
- **Result (1,549 train queries, out-of-fold, no date filter; date filter in brackets):**
  - The selector's top 5 misses the pool's best by more than 0.05 TM for 279 queries, 18% (302,
    19.5%). Pool best 0.507 there, selector's first pick 0.349. 73 (70) of them lose a usable
    template: the pool has TM ≥ 0.45, the selector's top 5 does not.
  - These misses cost 0.022 of the 0.030 TM per query between the selector's top 5 and the pool.
  - The missed best template is ranked 17th by the selector (median); 43% are ranked below 20th.
  - **Lone finds:** 61% of missed best templates were pooled by only one method (30% for queries
    not missed), at rank 3 to 8 in that method (median 6). Sources: john 36, twotower 30, emb 30,
    kmer3 25, m5 17, m2 16, m4 10, mmseqs 7.
  - **Consensus works against them:** their structural consensus with the top 5 is 0.23, against
    0.31 for what the selector picked; for 38% of misses it is clearly lower.
  - Sequence identity does not separate them (0.36 for both), and same Rfam family plays no role.
  - **Partial templates:** 45% of missed best templates are shorter than 0.7 × the query (32% when
    not missed).
  - **Harder queries:** only 25% of missed queries have a same-family template (43% when not
    missed); short queries are missed more (22% of queries up to 40 nt, 9% above 150 nt).
- **Interpretation:** the selector misses templates that look unusual to every signal it has: found
  by one method, structurally unlike the consensus, often partial. Next: coverage features (partial
  templates) and query-difficulty features (when to trust consensus less), then a top-5 that keeps
  one slot for a strong lone find.

---

## Step 22. Selector improvement, steps 2 and 3: coverage and query-difficulty features

- **Notebook:** `selector-v5` version 2 (CPU).
- **Added (on top of the reference, LambdaRank ranker + v4 features):**
  - Coverage (`c_*`, 6 features): from a traceback of the end-gap-free sequence alignment of each
    pooled pair, the share of the query and of the template that is aligned, identity on the aligned
    part, identical residues ÷ query length, internal gap runs and gap share. Checked on toy pairs
    (a template covering half the query gives 0.5).
  - Query difficulty (`g_*`, 12 features): pool size, how many different first picks the methods
    make, share of lone finds in the pool, the pool's best consensus / identity / coverage and each
    candidate's distance from them, the candidate's best rank over all methods, share of paired
    nucleotides in the query's fold, log query length.
- **Result (difference from the reference, 95% interval, 1,549 train queries out-of-fold):**

| Variant | Date filter | best TM@1 | best TM@5 |
|---|---|---|---|
| + coverage | no | −0.001 (−0.003 to +0.002) | −0.001 (−0.002 to +0.001) |
| + query | no | +0.001 (−0.002 to +0.003) | +0.001 (−0.001 to +0.002) |
| + both | no | −0.001 (−0.004 to +0.002) | −0.000 (−0.002 to +0.002) |
| + coverage | yes | +0.001 (−0.001 to +0.004) | +0.000 (−0.001 to +0.001) |
| + query | yes | +0.000 (−0.002 to +0.003) | −0.001 (−0.002 to +0.001) |
| + both | yes | +0.001 (−0.002 to +0.003) | +0.000 (−0.002 to +0.002) |

  Validation (159 queries) is the same: no interval excludes zero. The 279 badly missed queries stay
  missed (median rank of the best template still 17).
- **Interpretation:** neither is kept. Coverage comes from the same sequence alignment the methods
  already score, and the length ratio already flags partial templates. Query-level features are
  constant within a query, so a ranker that compares candidates of one query gains little from them.
  The missed templates are not hidden by a missing view of the alignment; nothing the selector can
  compute from sequence singles them out. Next: change how the five are picked (keep a slot for the
  strongest lone find), which needs no new information, and structure-based evidence (base-pair
  agreement) as genuinely new information.

---

## Step 23. Selector improvement: keeping slots for lone finds

- **Notebook:** `selector-v5` version 3 (CPU). The reference model is unchanged; only how the five
  templates are chosen from its scores changes (template 1 stays the same).
- **Tried:** top 4 (or 3) by score, then 1 (or 2) slots for: the best-scored lone find (pooled by one
  method only); the lone find ranked highest by the method that found it; or the best-scored template
  whose structure differs from every one already picked (template-template TM < 0.5).
- **Result (best TM@5 difference from the reference, 95% interval, 1,549 train queries out-of-fold;
  no filter / date filter):**

| Slots kept for | 1 slot | 2 slots |
|---|---|---|
| Lone find, by selector score | −0.001 (−0.001 to +0.000) / −0.001 (−0.002 to −0.000) | −0.002 (−0.003 to −0.001) / −0.002 (−0.003 to −0.000) |
| Lone find, by its method's rank | −0.000 (−0.002 to +0.001) / −0.001 (−0.002 to +0.001) | −0.003 (−0.005 to −0.001) / −0.003 (−0.004 to −0.001) |
| Structurally different template | +0.000 (−0.001 to +0.001) / +0.000 (−0.001 to +0.001) | −0.002 (−0.003 to −0.001) / +0.000 (−0.001 to +0.001) |

  Validation agrees: no variant is better. One lone-find slot rescues 39 to 98 queries but costs
  more (54 to 127 worse).
- **Interpretation:** not kept. Most lone finds are poor templates, and the good ones look the same
  as the poor ones to every signal we have, so a slot spent on them loses as often as it wins. With
  Steps 22 and 23, the cheap ideas are used up: the selector picks about as well as sequence-derived
  information allows. The remaining 0.03 TM gap to the pool needs new evidence (base-pair agreement
  from template structures, template quality), or we accept it and measure the effect in RNAPro.

---

## Step 24. RiboSeek (structural tokens) added: our re-implementation of the search

- **Notebooks:** `riboseek-tokens-oof` (T4 GPU, 7 min), `riboseek-scores` (CPU, 2 min), then
  `selector-v4` version 4. Private dataset `alizehadeel/riboseek-tokens` holds the team's token data
  (`tokens_dataset.jsonl`), the released model and its saved validation/test predictions.
- **Why a re-implementation:** `riboseek.zip` has the token model and the search *results*, not the
  search code. The search is rebuilt in the style of the other team methods and marked as ours.
- **Tokens:** the team's model (RS-20 token per nucleotide) was trained on all train chains, so
  for train queries it was retrained 5 times on the two-tower's family folds with the notebook's exact
  recipe. Out-of-fold token accuracy 26.4% (folds 22.9% to 30.9%); the released model gets 48.0% on
  train chains it has seen, 27.0% on validation and 29.1% on test, exactly the team's numbers, and
  reproduces its saved validation probabilities (largest difference 0.0002).
- **Search:** the query's predicted tokens are aligned end-gap-free (gap −2) against each template's
  real tokens. Three scorings: predicted top RS-80 token (match +2 / mismatch −1), token log-odds
  `log(p(template token) ÷ background)` clipped to ±3, and log-odds only where bases agree. The one
  used (`rs`) was chosen on the train queries only: **token log-odds** (train best TM@5 0.413 against
  0.367 and 0.377). **Check:** validation mean top-1 TM 0.349, against the team's 0.348
  (`pred_rs80_top1`) and 0.344 (`pred_rs20_logp`).
- **Keep test (leave-one-out from all methods, evaluation B):** RiboSeek adds the most of any team
  method: pool +0.0026 (+0.0019 to +0.0033) without the filter and with it; 102 / 77 queries get a
  better template; it is the only source of a better template for 102 queries, 56 of them usable
  (TM ≥ 0.45), more usable ones than even the two-tower (41). Selector not significantly worse
  (TM@5 −0.002, −0.004 to +0.001; TM@1 +0.004, +0.000 to +0.008). **Kept.**
- **Side effect:** with RiboSeek in the pool, Method 2's gain without the date filter is no longer
  significant (+0.0001, −0.0000 to +0.0004; 11 queries; only source for 8), so the rule drops it
  (with the date filter it still passes: +0.0002, +0.0000 to +0.0004). Rule's set: twotower, mmseqs,
  kmer3, john, m4, emb, m5, rs. Decision on Method 2 left to the team.
- **Selector (ranker + new features) with the rule's set:** train out-of-fold 0.457 / 0.497 (TM@1 /
  TM@5, unchanged), date filter 0.407 / 0.445 (from 0.404 / 0.444); validation 0.420 / 0.460 (from
  0.428 / 0.471), date filter 0.409 / 0.436. Pool ceiling 0.527 → 0.529 (train) and pool size 49 →
  54. As with every method so far, the selector rarely picks the new templates: RiboSeek's finds are
  in the pool, but the selector's results barely move.

---

## Step 25. Keep rule against a random method

- **Notebook:** `selector-v4` version 5 (CPU).
- **Rule tested:** keep a method if it is the only source of a good template (pool best TM ≥ 0.45,
  lost by more than 0.01 without it) for more train queries (out-of-fold) than a method that pools 10
  random allowed templates per query, with and without the date filter; the selector must not get
  significantly worse. Random method: 20 seeds, each added on top of all ten real methods; the bar is
  the largest count over the seeds (the mean is also reported).
- **Random method:** 4.9 good unique finds on average, at most 9 (no filter); 5.7 and 11 with the date
  filter. About 11% of queries have a good template no method pools, so random picks hit some of them.
- **Result (good unique finds, train queries; no filter / date filter):**

| Method | Good unique finds | Beats random maximum (9 / 11) | Beats random mean (4.9 / 5.7) |
|---|---|---|---|
| RiboSeek | 56 / 36 | yes | yes |
| Two-tower | 41 / 27 | yes | yes |
| Method 3 (emb) | 19 / 12 | yes | yes |
| john | 18 / 12 | yes | yes |
| 3-mer | 17 / 9 | no (date) | yes |
| MMseqs2 | 10 / 3 | no | no (date) |
| Method 5 | 8 / 7 | no | yes |
| Method 2 | 5 / 4 | no | no (date) |
| Method 4 | 2 / 0 | no | no |
| Method 1 | 0 / 0 | no | no |

- **Selector with the strict rule's set** (original four + emb + RiboSeek; the rule was applied only to
  the team's methods, the original four stay): train out-of-fold 0.459 / 0.496 (TM@1 / TM@5, against
  0.457 / 0.497 with all eight), date filter 0.408 / 0.444; validation 0.428 / 0.464, date filter
  0.404 / 0.435. Pool ceiling 0.529 → 0.524, pool 54 → 45 candidates. The selector does not change.
- **Interpretation:** a method with fewer than about 10 good unique finds rescues no more RNAs than
  random picks would. Methods 1, 2 and 4 are at chance level under either bar; Method 5 depends on the
  bar. Of the original four, 3-mer and MMseqs2 would also fail the strict bar.
- **Decision (team, 2026-11-18): the strict bar** (more good unique finds than the random method's
  best seed) is the preferred rule. Methods 1, 2, 4 and 5 are below it, but the team has postponed
  dropping them; for experiments the six-method set (twotower, mmseqs, kmer3, john, emb, rs) is used. The rule is applied to the team's methods; the original four stay
  for now (applying it to them would also drop 3-mer and MMseqs2, untested in the selector).

---

## Step 26. Selector improvement: base-pair agreement (running)

- **Notebook:** `selector-v5` version 4 (CPU), pushed 2026-11-18; results not yet read.
  Method set: the six kept methods (Step 25). Variants: reference (ranker + v4 features) and
  reference + base-pair features (`b_*`).
- **Real base pairs** of every library template are read from its 3D file (`chains/<id>.pdb` of
  `dataprep`, mapped to sequence positions with `residue_map.tsv`): A-U, G-C and G-U pairs whose
  N1 (purine) to N3 (pyrimidine) distance is under 3.5 Å, at least 4 apart, each residue in one pair at
  most (closest first). Checked locally on 250 real chains: tRNAs come out as cloverleaves; 46.9% of
  residues paired; ViennaRNA's predicted folds agree with the real pairs at F1 0.59 (median 0.69).
- **Features (through the end-gap-free sequence alignment of each pooled pair):** share of the
  query's predicted pairs landing on real template pairs (`b_recall`), share of the template's
  aligned real pairs landing on predicted pairs (`b_precision`), share of the template's real pairs
  whose two aligned query bases can pair (`b_compat`, and per half query length `b_compat_q`),
  dot-bracket alignment of the query's fold against the template's real structure (`b_struct_true`),
  and the template's paired share. The query's own structure is never used.
- **Checks on all 1,884 chains:** 48.1% of residues in a real pair (ViennaRNA predicts 60.4%);
  ViennaRNA vs real pairs F1 0.62 (median 0.70); 40 chains with no real pair.
- **Result (reference + base pairs minus reference, 95% interval):**

| Queries | Date filter | best TM@1 | best TM@5 | hit@5 |
|---|---|---|---|---|
| 1,549 train, out-of-fold | no | +0.003 (+0.000 to +0.007) | **+0.003 (+0.001 to +0.004)** | 0.813 → 0.823 |
| 1,549 train, out-of-fold | yes | **+0.003 (+0.000 to +0.006)** | **+0.005 (+0.003 to +0.008)** | 0.806 → 0.831 |
| 159 validation | no | −0.006 (−0.018 to +0.004) | −0.002 (−0.012 to +0.006) | 0.761 → 0.750 |
| 159 validation | yes | −0.001 (−0.011 to +0.006) | +0.001 (−0.000 to +0.003) | 0.787 → 0.787 |

  Selector with base pairs, train out-of-fold: 0.462 / 0.499 (TM@1 / TM@5), date filter 0.411 / 0.450.
- **Interpretation:** the first selector change since v4 with a significant gain on the 1,549 train
  queries, at top 5 with and without the date filter (larger with it), and it puts a good template in
  the top 5 for 1 to 2.5% more queries. Validation (159 queries) does not confirm it; its intervals
  include zero both ways. Real structural evidence helps where sequence features did not, but the gain
  is small (about a tenth of the 0.03 gap to the pool ceiling).
- **Method set note:** this run used the six methods above the strict bar of Step 25. The team has
  not yet decided to drop Methods 1, 2, 4 and 5 (2026-11-18: decision postponed); a rerun with all ten
  methods would show whether the base-pair gain holds there too.

---

## Step 27. Base-pair features with all ten methods

- **Notebook:** `selector-v5` version 5 (CPU, all ten methods; pool 57 candidates per query, 49 with
  the date filter).
- **Result (reference + base pairs minus reference, 95% interval):**

| Queries | Date filter | best TM@1 | best TM@5 | hit@5 |
|---|---|---|---|---|
| 1,549 train, out-of-fold | no | **+0.005 (+0.002 to +0.008)** | **+0.004 (+0.002 to +0.005)** | 0.805 → 0.818 |
| 1,549 train, out-of-fold | yes | +0.003 (−0.000 to +0.006) | **+0.004 (+0.002 to +0.006)** | 0.805 → 0.822 |
| 159 validation | no | +0.001 (−0.007 to +0.011) | +0.003 (−0.003 to +0.011) | 0.750 → 0.750 |
| 159 validation | yes | −0.001 (−0.005 to +0.002) | +0.001 (−0.002 to +0.004) | 0.800 → 0.800 |

- **Selector with base pairs, ten methods vs six (Step 26):**

| Queries | Date filter | Ten methods TM@1 / TM@5 | Six methods TM@1 / TM@5 | Pool ceiling (ten / six) |
|---|---|---|---|---|
| 1,549 train, out-of-fold | no | 0.462 / 0.499 | 0.462 / 0.499 | 0.530 / 0.524 |
| 1,549 train, out-of-fold | yes | 0.410 / 0.449 | 0.411 / 0.450 | 0.479 / 0.474 |
| 159 validation | no | 0.431 / 0.467 | 0.423 / 0.462 | 0.507 / 0.501 |
| 159 validation | yes | 0.408 / 0.440 | 0.402 / 0.436 | 0.471 / 0.463 |

- **Interpretation:** the base-pair gain holds with all ten methods and is a little larger at top 1
  (+0.005, interval above zero without the date filter). Validation now leans the same way but stays
  within noise. Ten methods and six give the same selector on the train queries; on validation ten is
  slightly ahead (+0.005 to +0.008, not tested for significance). Base-pair features are kept in the
  selector. The choice between six and ten methods does not change the selector's results so far.
- **Decision (team, 2026-11-18): all ten methods are kept**, including Methods 1, 2, 4 and 5, which
  are below the random-method bar of Step 25. The current selector is the ten-method LambdaRank
  ranker with v4 + base-pair features: 0.462 / 0.499 (TM@1 / TM@5, train out-of-fold).

---

## Step 28. RNAPro with the selector's templates

- **Result** (50 validation chains, date filter, finished 2026-11-19; selector minus john, 95% bootstrap):

  | | john | selector | difference | better / same / worse |
  |---|---|---|---|---|
  | picked templates, TM to query, first | 0.315 | 0.362 | +0.047 | — |
  | picked templates, TM to query, best of 5 | 0.365 | 0.396 | +0.031 | 29 / 16 / 5 |
  | adapted templates, no RNAPro, first | 0.311 | 0.306 | −0.005 [−0.025, 0.016] | 16 / 13 / 21 |
  | adapted templates, no RNAPro, best of 5 | 0.351 | 0.350 | −0.000 [−0.020, 0.025] | 15 / 13 / 22 |
  | RNAPro, prediction 1 | 0.665 | 0.685 | +0.020 [−0.011, 0.060] | 15 / 22 / 13 |
  | RNAPro, best of 5 | 0.716 | 0.719 | +0.003 [−0.004, 0.010] | 15 / 26 / 9 |

- **Reading:** the selector picks clearly better templates, but the edge is lost in the adaptation
  step: refinement confidence and noise (sd = 0.8 − score) use john's score of the pair, and 36% of
  the selector's picks are templates john never scored (score 0), so they get the most noise and the
  weakest refinement. RNAPro's first prediction is 0.020 TM better, not significant on 50 chains.
- **Confound to fix before a final claim:** adapt both template sets the same way, independent of
  john's score (no noise, fixed confidence), then compare again. Done in Step 30.

## Step 30. Plain templates (alignment only) for both sets

- **What:** `rnapro-inputs` v3 also writes `john_templates_plain.csv` and `selector_templates_plain.csv`:
  the same alignment and coordinate copy, without john's refinement and noise, so both template sets
  are treated identically. New GPU notebooks `rnapro-run-john-plain` and `rnapro-run-selector-plain`;
  `rnapro-score` v5 scores all eight sources on the same 50 chains.
- **Result** (selector minus john, 95% bootstrap, better / same / worse):

  | | john | selector | difference | b / s / w |
  |---|---|---|---|---|
  | plain templates alone, first | 0.318 | 0.327 | +0.009 [−0.012, 0.030] | 20 / 11 / 19 |
  | plain templates alone, best of 5 | 0.359 | 0.375 | +0.017 [−0.004, 0.043] | 19 / 17 / 14 |
  | RNAPro + plain, prediction 1 | 0.670 | 0.683 | +0.014 [−0.013, 0.041] | 20 / 19 / 11 |
  | RNAPro + plain, best of 5 | 0.710 | 0.716 | +0.007 [−0.004, 0.022] | 13 / 26 / 11 |

  Refinement + noise hurt the templates alone (john −0.007, selector −0.021 to −0.025, both
  significant), but RNAPro barely notices: plain vs adapted inputs change its TM by −0.006 to +0.005,
  none significant. Share of chains with best TM ≥ 0.45 after RNAPro: 84% in all four runs.
- **Reading:** with either adaptation, RNAPro + the selector's templates is ahead of RNAPro + john's
  (+0.014 to +0.020 prediction 1, +0.003 to +0.007 best of 5), more chains better than worse, but no
  interval excludes zero. 50 chains is too few: at this effect size about 200 chains are needed.

## Step 31. Plain templates on all 123 usable validation chains

- **What:** only 123 of the 159 validation chains have a usable MSA, so 73 chains were added
  (`rnapro-inputs` v4 writes `subset_rest.csv`; the first 50 and their templates are unchanged). New GPU
  notebooks `rnapro-run-john-plain-rest` and `rnapro-run-selector-plain-rest`; `rnapro-score` v6 joins
  them with the 50-chain runs ("all"). No chain failed.
- **Result** (selector minus john, plain templates, 95% bootstrap, better / same / worse):

  | | chains | john | selector | difference | b / s / w |
  |---|---|---|---|---|---|
  | templates alone, first | 123 | 0.351 | 0.377 | **+0.026 [+0.002, +0.050]** | 48 / 34 / 41 |
  | templates alone, best of 5 | 123 | 0.412 | 0.422 | +0.011 [−0.010, +0.033] | 47 / 46 / 30 |
  | RNAPro, prediction 1 | 123 | 0.705 | 0.708 | +0.003 [−0.012, +0.018] | 31 / 63 / 29 |
  | RNAPro, best of 5 | 123 | 0.747 | 0.746 | −0.001 [−0.008, +0.007] | 25 / 65 / 33 |
  | RNAPro, prediction 1, new 73 only | 73 | 0.729 | 0.725 | −0.005 [−0.019, +0.012] | 11 / 44 / 18 |

  Share of chains with best TM ≥ 0.45 after RNAPro: 88.6% for both.
- **Reading:** the selector's first template is significantly better than john's (+0.026 TM), but
  RNAPro's output is the same with either set. The +0.014 to +0.020 lead on the first 50 chains did
  not hold on the next 73; it was chance. RNAPro turns templates of TM ~0.35–0.42 into predictions of
  ~0.71–0.75, so on these chains its accuracy comes mostly from the model and MSA, not from which of
  these good-enough templates it gets. Template choice could still matter on template-poor chains,
  which are few here (89% reach TM 0.45).

## Step 32. Control: each chain's own structure as the template

- **What:** the first 50 validation chains each get their own experimental C1′ structure as all five
  templates (`native_templates.csv`, same file format and gap filling as the other template files);
  `rnapro-run-native` (GPU, 86 min), scored by `rnapro-score` v8.
- **Result** (50 chains): RNAPro + own structure 0.812 / 0.812 (prediction 1 / best of 5), against
  RNAPro + john plain 0.670 / 0.710 and + selector plain 0.683 / 0.716. Difference vs john
  +0.142 [+0.100, +0.189] at prediction 1 (45 / 2 / 3 chains better / same / worse), +0.102
  [+0.064, +0.147] best of 5. Median 0.869, minimum 0.208; 92% of chains reach TM 0.45.
- **Reading:** our template pipeline works and RNAPro does use templates: a perfect template raises
  its TM by 0.14. But it does not copy them (0.81, not 1.0), and the templates any search can find
  here (TM ~0.35–0.42 to the query after alignment) are far from perfect, so in that range RNAPro
  relies on the MSA and its own model, and a +0.026 better template does not move its output.

## Step 33. Test set, run once (2026-11-19/20)

- **What:** `selector-test` trains the current selector (ten methods, LambdaRank, v4 + base-pair
  features) on the 1,549 train chains and scores the 176 test chains (labels `pairs_test.parquet`);
  `rnapro-inputs-test` builds plain templates for the 141 test chains with a usable MSA;
  `rnapro-run-john-test` and `rnapro-run-selector-test` (GPU, about 3 h each); `rnapro-score-test`.
- **Template level, 176 chains, date filter:** selector best TM@1 0.395 / TM@5 0.425 vs john 0.351 /
  0.398: +0.043 [+0.031, +0.056] and +0.026 [+0.017, +0.036]; pool ceiling 0.453, best in library 0.468.
- **RNAPro, 141 chains:** john 0.724 / 0.764 (prediction 1 / best of 5), selector 0.719 / 0.758:
  −0.005 [−0.027, +0.018] and −0.006 [−0.012, −0.001]. Templates alone after alignment: +0.010 /
  +0.007, not significant.
- **Reading:** the test set confirms both validation findings: the selector picks significantly better
  templates, and RNAPro used as released does not turn that into better structures (at best of 5 it
  is marginally worse).

- **Pipeline** (pushed 2026-11-18 by `rnapro/run_rnapro_selector_chain.sh`, one notebook after the other):
  1. `selector-v5` version 6: the current selector (ten methods, ranker + v4 + base-pair features,
     fitted on the 1,549 train queries) writes its top 5 for every validation query
     (`selector_top5_val.csv`, both date settings).
  2. `rnapro-inputs`: the same 50 chains as Step 18; the selector's top 5 (date filter) are adapted
     exactly like john's (same alignment, refinement, noise and seed; refinement and noise are driven
     by john's score of that query–template pair, a property of the pair, not of the method that
     picked it) → `selector_templates.csv`. john's file is rebuilt by the unchanged code.
  3. `rnapro-run-selector` (GPU): `rnapro-run` with only the template file and tag changed, so the
     john run's outputs stay as they are.
  4. `rnapro-score`: scores both runs and both template sets; paired comparisons (selector minus
     john, prediction 1 and best of 5, 95% bootstrap interval) in `rnapro_compare.csv`.
- **If the chain stopped** (it runs from the laptop), push the remaining notebooks by hand in that
  order: `kaggle kernels push -p <folder>`.

---

## Step 29. Selector training tweaks and ensembles (no change)

- **What** (`selector/selector_v6`, run 2026-11-18 while RNAPro ran): same pool (ten methods), same
  features (v4 + base pairs), same evaluations; only the model changes. Reference = the current
  selector (LambdaRank). Seven single models (steeper gains 2^(l/4)−1, truncation 5, slower /
  subsampled trees, LightGBM regression on TM, rank_xendcg, the old HistGradientBoosting trees, a bag
  of five seeds) and five ensembles (within-query percentile ranks averaged).
- **Result** (train out-of-fold, difference from the current selector, best TM@1 / @5):

  | Variant | no date filter | date filter |
  |---|---|---|
  | steeper gains | −0.000 / +0.001 | +0.001 / +0.001 |
  | top-5 truncation | −0.001 / +0.001 | −0.001 / +0.001 |
  | slower trees | +0.001 / +0.001 | +0.000 / −0.001 |
  | regression on TM | −0.003 / **−0.002** | −0.003 / **−0.004** |
  | rank_xendcg | **−0.005** / **+0.003** | −0.001 / +0.001 |
  | old trees | **−0.005** / **−0.004** | **−0.004** / **−0.005** |
  | bag of five | +0.002 / +0.001 | +0.001 / −0.000 |
  | ensemble, all seven | +0.002 / +0.000 | **+0.003** / +0.001 |

  Bold = 95% interval excludes zero. Validation agrees (all within ±0.01, the all-seven ensemble
  +0.004 TM@1 with the date filter, TM@5 unchanged).
- **Decision:** keep the current selector. The best tweaks gain at most 0.003 TM, against a 0.031
  gap to the pool ceiling at top 5; the remaining gap is not a training problem, it needs
  information the features do not have (Steps 21–23). Every variant's validation top 5 is saved
  (`selector6_top5_val.csv`) if one is ever needed.

---

## Open items

- Who runs the oracle three-arm test and stop rule from the project spec (steps 1 to 3).
- Date leakage for a CASP15 comparison: 1,092 train chains are dated before 2022-05-27.
- More template-finding methods, aimed at the queries where no method pools a similar template.
  All three team methods from `all_methods.zip` are kept under the new keep rule (Step 19; under
  the old rule only Method 4 was). New methods should target the ~11% of queries with a similar
  template that no method pools.
- Selector: still 0.03 TM below the pool ceiling at top 5 (Step 19); the missed templates are
  mostly ranked far down, so more pair features (e.g. aligned structural coverage) are next.
- The test split (176 chains) was used once (Step 33); it must not be used for any further tuning.
- Labels were made with US-align's default atom (C3'); the paper scores on C1'.
- Kaggle GPU used so far: about 9.5 of 30 weekly hours. Nothing is committed to git.
