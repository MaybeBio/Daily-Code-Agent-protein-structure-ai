"""Supplement S2 on the compendium: Biohub's ESMC-6B layer-60 SAE latents labeled with the release's terms, and the labels
compared with Biohub's descriptions as version one compared its own.

E3 reads the SAE's 16,384 latents (TopK 64) at block 59 as a `selection` pair over the atlas set, so every latent has a
best global term by training AUROC under the observation rule, that term's AUROC on the test proteins, which score only
experimental and signature labels, and the local labels the atlas study's frozen criteria select with BH (`scores`).
`label_summary` reports them as S2 reported version one's: how many latents carry a label, and how well the labels predict
their terms on held-out proteins, with average precision against prevalence from the missing-annotation correction.

`agreement` repeats version one's frozen comparison with Biohub's agent-written descriptions (annotation_vocabulary
`scripts/study_semantic_comparison/similarity`, protocol `direct-semantic-representatives-20260910-v1`) on the release's
terms. Each latent's representatives are fixed by rule before a description is read (`representatives`): globally its best
training term when that AUROC reaches the atlas study's 0.6, locally its selected release term with the largest mean paired
contrast (intrinsic terms have no text). A term's document joins its name and definition, the release having no synonyms; a
description joins Biohub's summary and activation pattern. Word TF-IDF (unigrams and bigrams, sublinear term frequency, L2
norm) is fit on every release term's document, and a representative scores a description by cosine. A latent's own
description is set against the descriptions of its stratum, Biohub's category (a missing one apart) by word count cut at 50,
100, 200 and 400 (`matched_partners`): the win probability is the share of the stratum its own beats, ties a half, and the
paired excess its own score minus the mean over 1,000 within-stratum permutations, whose population means give a one-sided
p (`summarize_scores`). Both functions are version one's estimator, checked against its code in the tests. A latent without
a representative stays in its stratum as a control and leaves the estimand, version one's missingness rule.

Symbols: f latents; t terms scored; p permutations; g a stratum's latents; v term documents; d TF-IDF features.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from collections.abc import Sequence

from .bootstrap import median_interval


FEATURE_TABLE = {"repo": "biohub/ESMC-SAE-Features", "revision": "c96112e96449231055d73ae6cd0f1dc61912f44b",
                 "file": "uniref90_feature_table.parquet"}  # version one's pin
DESCRIPTION_FIELDS = ("summary", "activation_pattern")
WORD_EDGES = (50, 100, 200, 400)
PERMUTATIONS = 1000
BOOTSTRAP = 1000
SEED = 24895
MIN_GLOBAL_AUROC = 0.6  # the atlas study's global selection threshold
ARMS = ("global", "local")


def descriptions(table: pd.DataFrame) -> pd.DataFrame:
    """Biohub's descriptions as version one read them: `feature_id`, `semantic_text` (each field of `DESCRIPTION_FIELDS`
    stripped, the empty ones left out, joined by a newline) and `category`; a latent with no text is left out."""
    text = ["\n".join(part for part in (str(value).strip() for value in values) if part)
            for values in zip(*(table[field] for field in DESCRIPTION_FIELDS), strict=True)]
    frame = pd.DataFrame({"feature_id": table["feature_id"].to_numpy(dtype=np.int64), "semantic_text": text,
                          "category": table["category"].to_numpy()})
    return frame[frame["semantic_text"].str.strip() != ""].reset_index(drop=True)


def term_documents(labels: Sequence[str], definitions: Sequence[object]) -> list[str]:
    """Each term's document, its name and definition joined by '. ' with a missing part left out (version one's document
    without synonyms, which the release does not keep)."""
    return [". ".join(part for part in (str(label), "" if pd.isna(definition) else str(definition)) if part)
            for label, definition in zip(labels, definitions, strict=True)]


def representatives(scores: pd.DataFrame, labels: pd.DataFrame, vocabulary_size: int, *,
                    min_auroc: float = MIN_GLOBAL_AUROC) -> pd.DataFrame:
    """Each latent's global and local representative token, -1 where it has none: its best global term when the training
    AUROC reaches `min_auroc`, and its selected release local term with the largest mean paired contrast, the smaller token
    on a tie."""
    # scores: one row per latent in pole order (`pole`, `best_term`, `best_auroc`); labels: `pole`, `term`, `mean_difference`
    if not np.array_equal(scores["pole"].to_numpy(), np.arange(len(scores))):
        raise ValueError("The score table must hold one row per latent, in pole order.")
    best_auroc = scores["best_auroc"].to_numpy(dtype=np.float64)  # (f,)
    global_term = np.where(best_auroc >= min_auroc, scores["best_term"].to_numpy(dtype=np.int64), -1)  # (f,), NaN fails
    release = labels[labels["term"] < vocabulary_size]
    best = (release.sort_values(["pole", "mean_difference", "term"], ascending=[True, False, True], kind="mergesort")
            .drop_duplicates("pole"))
    local_term = np.full(len(scores), -1, dtype=np.int64)  # (f,)
    local_term[best["pole"].to_numpy(dtype=np.int64)] = best["term"].to_numpy(dtype=np.int64)
    return pd.DataFrame({"feature_id": np.arange(len(scores)), "global": global_term, "local": local_term})


def tfidf_scores(documents: Sequence[str], rows: np.ndarray, texts: Sequence[str], *, block: int = 128) -> np.ndarray:
    """Cosine of word TF-IDF vectors between the documents of `rows` and every text: unigrams and bigrams, sublinear term
    frequency and L2 norm, fit on every document, as version one scored its representatives."""
    # rows: (t,) document indices
    from sklearn.feature_extraction.text import TfidfVectorizer

    vectorizer = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), dtype=np.float32, sublinear_tf=True)
    document_vectors = vectorizer.fit_transform(documents)  # (v, d)
    query_vectors = vectorizer.transform(texts)  # (f, d)
    scores = np.empty((len(rows), len(texts)), dtype=np.float32)  # (t, f)
    for start in range(0, len(rows), block):
        scores[start:start + block] = (document_vectors[rows[start:start + block]] @ query_vectors.T).toarray()  # (b, f)
    return scores  # (t, f)


def matched_partners(features: pd.DataFrame, n_permutations: int,
                     seed: int) -> tuple[np.ndarray, list[np.ndarray], list[dict[str, object]]]:
    """Uniform permutations within strata of category by word count, in canonical feature order (version one's)."""
    if features["feature_id"].duplicated().any():
        raise ValueError("Duplicate feature ids.")
    word_count = features["semantic_text"].fillna("").str.split().str.len().to_numpy()  # (f,)
    bins = np.searchsorted(WORD_EDGES, word_count, side="right")  # (f,)
    categories = features["category"].fillna("<missing>").astype(str).to_numpy()  # (f,)
    feature_ids = features["feature_id"].to_numpy()  # (f,)
    groups, records = [], []
    for category, length_bin in sorted(set(zip(categories, bins, strict=True))):
        indices = np.flatnonzero((categories == category) & (bins == length_bin))  # (g,)
        indices = indices[np.argsort(feature_ids[indices])]  # (g,)
        groups.append(indices)
        records.append({"category": category, "length_bin": int(length_bin), "features": len(indices),
                        "degenerate": len(indices) <= 1})
    generator = np.random.default_rng(seed)
    partners = np.tile(np.arange(len(features), dtype=np.int32), (n_permutations, 1))  # (p, f)
    for group in groups:  # (g,)
        for permutation in range(n_permutations):
            partners[permutation, group] = generator.permutation(group)  # (g,)
    return partners, groups, records  # (p, f), list of (g,), metadata


def summarize_scores(scores: np.ndarray, term_rows: np.ndarray, partners: np.ndarray, groups: list[np.ndarray], seed: int,
                     bootstrap_replicates: int = BOOTSTRAP) -> tuple[pd.DataFrame, dict[str, object], np.ndarray]:
    """Per latent its own score, matched control mean, paired excess, win probability and midrank in its stratum, and the
    population estimands (version one's): a latent is in the estimand only if its representative scores every description
    of its stratum."""
    # scores: (t, f); term_rows: (f,); partners: (p, f); groups: (g,) each
    features = np.arange(len(term_rows))  # (f,)
    observed = scores[term_rows, features].astype(np.float64)  # (f,)
    controls = scores[term_rows[None, :], partners].astype(np.float64)  # (p, f)
    finite = np.isfinite(observed)  # (f,)
    for group in groups:  # (g,)
        for feature in group:
            finite[feature] &= np.isfinite(scores[term_rows[feature], group]).all()
    control_mean = np.full(len(features), np.nan)  # (f,)
    control_mean[finite] = controls[:, finite].mean(axis=0)  # (n,)
    excess = observed - control_mean  # (f,)
    win = np.full(len(features), np.nan)  # (f,)
    rank = np.full(len(features), np.nan)  # (f,)
    stratum_size = np.zeros(len(features), dtype=np.int32)  # (f,)
    for group in groups:  # (g,)
        for feature in group:
            candidates = scores[term_rows[feature], group]  # (g,)
            candidates = candidates[np.isfinite(candidates)]  # (v,)
            stratum_size[feature] = len(candidates)
            if not len(candidates) or not np.isfinite(observed[feature]):
                continue
            wins = np.count_nonzero(observed[feature] > candidates)
            ties = np.count_nonzero(observed[feature] == candidates)
            win[feature] = (wins + 0.5 * ties) / len(candidates)
            rank[feature] = 1 + np.count_nonzero(candidates > observed[feature]) + 0.5 * (ties - 1)
    frame = pd.DataFrame({"observed_score": observed, "matched_control_mean": control_mean, "semantic_excess": excess,
                          "matched_win_probability": win, "matched_midrank": rank, "matched_description_count": stratum_size,
                          "included_in_estimand": finite})
    if not finite.any():
        return frame, {"features": len(features), "included": 0, "missing": len(features)}, np.zeros(0)  # frame, metadata, (0,)
    permutation_means = controls[:, finite].mean(axis=1)  # (p,)
    included_excess = excess[finite]  # (n,)
    generator = np.random.default_rng(seed)
    bootstrap_means = np.empty(bootstrap_replicates)  # (r,)
    for index in range(bootstrap_replicates):
        bootstrap_means[index] = generator.choice(included_excess, len(included_excess), replace=True).mean()
    observed_mean = float(observed[finite].mean())
    summary = {"features": len(features), "included": int(finite.sum()), "missing": int((~finite).sum()),
               "mean_same_feature": observed_mean, "mean_matched_control": float(permutation_means.mean()),
               "mean_semantic_excess": float(included_excess.mean()), "median_semantic_excess": float(np.median(included_excess)),
               "mean_excess_feature_bootstrap_95ci": np.quantile(bootstrap_means, [0.025, 0.975]).tolist(),
               "mean_matched_win_probability": float(np.mean(win[finite])),
               "median_matched_win_probability": float(np.median(win[finite])),
               "win_probability_chance": 0.5, "semantic_excess_chance": 0,
               "permutation_means_95interval": np.quantile(permutation_means, [0.025, 0.975]).tolist(),
               "one_sided_permutation_p": float((1 + np.count_nonzero(permutation_means >= observed_mean)) / (len(partners) + 1))}
    return frame, summary, permutation_means  # frame, metadata, (p,)


def agreement(described: pd.DataFrame, chosen: pd.DataFrame, documents: Sequence[str], *, permutations: int = PERMUTATIONS,
              seed: int = SEED, bootstrap_replicates: int = BOOTSTRAP) -> tuple[pd.DataFrame, dict[str, object]]:
    """Each arm's representatives scored against the descriptions with version one's matched estimator: per latent and arm
    the scores of `summarize_scores`, and per arm its population summary, with the strata."""
    # described: `descriptions`; chosen: `representatives`; documents: one per vocabulary token, in token order
    order = described.merge(chosen, on="feature_id", how="left", validate="one_to_one")
    partners, groups, strata = matched_partners(order, permutations, seed)  # (p, f), list of (g,), metadata
    tokens = np.array(sorted({int(token) for arm in ARMS for token in order[arm].fillna(-1) if token >= 0}), dtype=np.int64)  # (t,)
    row_of = {int(token): row for row, token in enumerate(tokens)}
    scores = tfidf_scores(documents, tokens, order["semantic_text"].tolist())  # (t, f)
    scores = np.vstack([scores, np.full((1, len(order)), np.nan, dtype=np.float32)])  # (t + 1, f): the last row, no representative
    frames, summaries = [], {}
    for arm in ARMS:
        term_rows = np.array([row_of.get(int(token), len(tokens)) for token in order[arm].fillna(-1)], dtype=np.int64)  # (f,)
        frame, summary, _ = summarize_scores(scores, term_rows, partners, groups, seed, bootstrap_replicates)
        frames.append(frame.assign(feature_id=order["feature_id"].to_numpy(), arm=arm, token=order[arm].fillna(-1).astype(np.int64),
                                   category=order["category"].to_numpy()))
        summaries[arm] = summary
    moved = np.count_nonzero(partners != np.arange(len(order))[None, :], axis=1)  # (p,)
    return pd.concat(frames, ignore_index=True), {
        "arms": summaries, "described": len(order), "scored_terms": len(tokens),
        "strata": strata, "degenerate_strata": sum(record["degenerate"] for record in strata),
        "mean_moved_features": float(moved.mean())}


def label_summary(scores: pd.DataFrame, labels: pd.DataFrame, inheritance: pd.DataFrame, vocabulary_size: int, *,
                  min_auroc: float = MIN_GLOBAL_AUROC) -> dict[str, object]:
    """The latents' labels as S2 reports them: global best terms and their held-out AUROC with bootstrap intervals over
    latents, local selection, average precision against prevalence before and after inheritance, and the dominant share."""
    # scores: E3's score table of the SAE pair; labels: its selected local pairs; inheritance: `missing.basis_scores`'s table
    best = scores["best_auroc"].to_numpy(dtype=np.float64)  # (f,)
    held_out = scores["held_out_auroc"].to_numpy(dtype=np.float64)  # (f,)
    labeled = best >= min_auroc  # (f,)
    per_latent = labels.groupby("pole").size()
    release = labels[labels["term"] < vocabulary_size]

    def median(values: np.ndarray) -> dict[str, float] | None:
        # values: (a,)
        finite = np.asarray(values, dtype=np.float64)
        finite = finite[np.isfinite(finite)]  # (a,)
        if finite.size == 0:
            return None
        interval = median_interval(finite)
        return {"estimate": interval.estimate, "low": interval.low, "high": interval.high, "units": int(finite.size)}

    return {
        "latents": len(scores), "with_testable_term": int(np.isfinite(best).sum()),
        "best_auroc": median(best), "global_labeled": int(labeled.sum()),
        "held_out_auroc": median(held_out), "held_out_auroc_labeled": median(held_out[labeled]),
        "local_labels": len(labels), "with_local_label": int(per_latent.size),
        "median_local_labels": float(per_latent.median()) if len(per_latent) else 0.0,
        "with_release_local_label": int(release["pole"].nunique()),
        "precision_before": median(inheritance["precision_before"].to_numpy()),
        "prevalence_before": median(inheritance["prevalence_before"].to_numpy()),
        "precision_after": median(inheritance["precision_after"].to_numpy()),
        "prevalence_after": median(inheritance["prevalence_after"].to_numpy()),
        "dominant": int(scores["dominant"].sum()), "dominant_share": float(scores["dominant"].mean()),
    }
