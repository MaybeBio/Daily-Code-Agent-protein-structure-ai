"""Masked-token pretraining of the annotation transformer on the token lists of an Annotation Vocabulary release.

A row is a protein's annotation entry: the vocabulary tokens of its terms, ascending. The model reads the entry with 15
percent of its tokens hidden (80 percent replaced by `<mask>`, 10 percent by another biological token, 10 percent kept) and
predicts the hidden ones, as `Synthyra/AT-Base` was trained. The vocabulary is the release's, so its size, padding token and
mask token come from `vocabulary.parquet`, and token zero is a real term, never padding. Training reads the `train` split
only and validation picks the checkpoint: the one with the lowest validation loss is `best/`, and it is the model that ships.
When training ends, `best/` is scored once on `validation` (the selection) and once on `test` at the same fixed hidden
positions, beside the train-frequency prior and a randomly initialized model on those positions, with 95 percent
cluster-bootstrap intervals, and the result is written to `evaluation.json` (Logan's rule, 2026-10-02: checkpoints are chosen on
validation and test metrics are reported). The test split is read once: a run refuses to evaluate again where `evaluation.json`
exists. `calibration` is never read.

A compendium release (`compendium`) is read as its module says: entries without organism terms, wrapped in `<bos>` and
`<eos>` to at most 64 tokens, training batches drawn over 0.9-identity clusters with entries cut and thinned, held-out entries
cut once, and intervals resampling the split's 0.5-identity clusters (`cluster_id` in `rows_<split>.parquet`). Specials are
never hidden.

    python -m annotation_transformer.pretrain --release <release dir> --output <dir> --experiment 2026-10-02_at_experimental_v1
    python -m annotation_transformer.pretrain ... --evaluate-only   # score an existing best/ once, for a run made before this rule
    python -m annotation_transformer.pretrain ... --push-only --hub-repo <repo>   # push best/ and the card files of the output directory
"""

from __future__ import annotations

import argparse
import json
import math
import random
import pyarrow as pa
import pyarrow.parquet as pq
import torch

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from torch import Tensor
from tqdm.auto import tqdm

from foundry.layers.cross_entropy import cross_entropy
from foundry.logging import Run, revision_of
from foundry.pilot import Pilot
from foundry.training import clip_grad_norm, set_seed
from . import compendium
from .config import AnnotationTransformerConfig
from .modeling import AnnotationTransformer


IGNORE_INDEX = -100
SPECIAL_ASPECT = "special"
TOP_K = (1, 5)
EVALUATION_FILE = "evaluation.json"
# What a run directory adds to `best/` on the Hub: the card, its record and figure, and the scores the card reports.
CARD_FILES = ("README.md", "model_card_record.json", "performance.png", EVALUATION_FILE)
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 42
INTERVAL_LEVEL = 0.95
SCORE_NAMES = ("loss", *(f"top{top}" for top in TOP_K))


@dataclass(frozen=True, slots=True)
class TokenSpace:
    """The biological and special tokens of a release's vocabulary; `bos` and `eos` when entries are wrapped in them."""

    terms: int
    pad: int
    mask: int
    size: int
    bos: int | None = None
    eos: int | None = None


def read_token_space(release: Path) -> TokenSpace:
    """The vocabulary's biological token count, its `<pad>` and `<mask>` ids and its total size.

    A vocabulary release's model reads bare entries; a compendium's appends the specials after its terms and wraps entries.
    """
    if compendium.is_compendium(release):
        terms = compendium.term_count(release)
        special = {name: terms + index for index, name in enumerate(compendium.SPECIALS)}
        return TokenSpace(terms, special["<pad>"], special["<mask>"], terms + len(special), special["<bos>"], special["<eos>"])
    table = pq.read_table(release / "vocabulary.parquet", columns=["token", "term_id", "aspect"]).to_pydict()
    special = {term: token for term, token, aspect in zip(table["term_id"], table["token"], table["aspect"], strict=True) if aspect == SPECIAL_ASPECT}
    terms = sum(aspect != SPECIAL_ASPECT for aspect in table["aspect"])
    if terms != min(special.values()) or len(table["token"]) != terms + len(special):
        raise ValueError("the vocabulary's special tokens must follow its biological tokens directly")
    return TokenSpace(terms, special["<pad>"], special["<mask>"], len(table["token"]))


def read_split(release: Path, split: str) -> dict[str, list[Any]]:
    """The protein id, bootstrap cluster and model input of every row of a held-out split of a release.

    A vocabulary release's cluster is its finest and its input the bare entry; a compendium's cluster is the 0.5-identity
    level and its input the entry cut once and wrapped (`compendium.held_out_entry`).
    """
    if not compendium.is_compendium(release):
        return pq.read_table(release / f"{split}.parquet", columns=["protein_id", "cluster_id", "annotation_tokens"]).to_pydict()
    space = read_token_space(release)
    rows = compendium.read_split(release, split)
    entries = [compendium.wrap(compendium.held_out_entry(entry, protein), space.bos, space.eos)
               for entry, protein in zip(rows.entries, rows.protein_id, strict=True)]
    return {"protein_id": rows.protein_id, "cluster_id": rows.c050, "annotation_tokens": entries}


def read_token_lists(release: Path, split: str) -> list[list[int]]:
    """The annotation entries of one split of a release as stored: a compendium's without organism terms, uncut and unwrapped."""
    if compendium.is_compendium(release):
        return compendium.read_split(release, split).entries
    return pq.read_table(release / f"{split}.parquet", columns=["annotation_tokens"]).column("annotation_tokens").to_pylist()


def collate(rows: Sequence[Sequence[int]], pad: int) -> tuple[Tensor, Tensor]:
    """Pad entries to the longest of the batch; returns the token ids and the mask that is 1 for a real token."""
    length = max(len(row) for row in rows)  # l
    input_ids = torch.full((len(rows), length), pad, dtype=torch.long)  # (b, l)
    attention_mask = torch.zeros((len(rows), length), dtype=torch.long)  # (b, l)
    for index, row in enumerate(rows):
        input_ids[index, : len(row)] = torch.tensor(row, dtype=torch.long)
        attention_mask[index, : len(row)] = 1
    return input_ids, attention_mask  # (b, l), (b, l)


def mask_for_mlm(
    input_ids: Tensor, attention_mask: Tensor, space: TokenSpace, probability: float, generator: torch.Generator,
) -> tuple[Tensor, Tensor]:
    """Hide a share of the terms: returns the corrupted ids and the labels, `IGNORE_INDEX` where nothing is hidden.

    Padding and specials (`<bos>`, `<eos>`) are never hidden.
    """
    # input_ids: (b, l); attention_mask: (b, l)
    eligible = attention_mask.bool() & (input_ids < space.terms)  # (b, l)
    chosen = (torch.rand(input_ids.shape, generator=generator) < probability) & eligible  # (b, l)
    # A row with nothing hidden would teach nothing; hide its first term.
    empty = ~chosen.any(dim=1)  # (b,)
    first = eligible.int().argmax(dim=1)  # (b,)
    chosen[empty, first[empty]] = True
    labels = torch.where(chosen, input_ids, torch.full_like(input_ids, IGNORE_INDEX))  # (b, l)
    action = torch.rand(input_ids.shape, generator=generator)  # (b, l)
    corrupted = input_ids.clone()  # (b, l)
    corrupted[chosen & (action < 0.8)] = space.mask
    replaced = chosen & (action >= 0.8) & (action < 0.9)  # (b, l)
    corrupted[replaced] = torch.randint(0, space.terms, (int(replaced.sum()),), generator=generator)
    return corrupted, labels  # (b, l), (b, l)


def masked_loss(model: AnnotationTransformer, input_ids: Tensor, attention_mask: Tensor, labels: Tensor) -> tuple[Tensor, Tensor, Tensor]:
    """Cross entropy at the hidden positions only, with the logits and labels it scored.

    The language-model head runs on the gathered hidden states, so the `(b, l, v)` logits tensor is never built.
    """
    # input_ids: (b, l); attention_mask: (b, l); labels: (b, l)
    hidden = model(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state  # (b, l, d)
    keep = labels != IGNORE_INDEX  # (b, l)
    logits = model.lm_head(hidden[keep]).float()  # (n, v)
    targets = labels[keep]  # (n,)
    return cross_entropy(logits, targets), logits, targets  # (), (n, v), (n,)


@dataclass(frozen=True, slots=True)
class Schedule:
    """Linear warmup then cosine decay to a share of the peak rate."""

    warmup: int
    steps: int
    floor: float

    def factor(self, step: int) -> float:
        if step < self.warmup:
            return (step + 1) / max(1, self.warmup)
        progress = min(1.0, (step - self.warmup) / max(1, self.steps - self.warmup))
        return self.floor + (1.0 - self.floor) * 0.5 * (1.0 + math.cos(math.pi * progress))


def batches(rows: list[list[int]], size: int, seed: int) -> Iterator[list[list[int]]]:
    """Endless shuffled batches of whole entries; each epoch reshuffles with its own seed."""
    epoch = 0
    while True:
        order = torch.randperm(len(rows), generator=torch.Generator().manual_seed(seed + epoch)).tolist()
        for start in range(0, len(order) - size + 1, size):
            yield [rows[index] for index in order[start:start + size]]
        epoch += 1


def training_batches(release: Path, space: TokenSpace, size: int, seed: int) -> Iterator[list[list[int]]]:
    """Endless training batches: a vocabulary release's whole entries, shuffled by epoch; a compendium's entries drawn one
    per 0.9-identity cluster, cut or thinned, and wrapped."""
    if not compendium.is_compendium(release):
        yield from batches(read_token_lists(release, "train"), size, seed)
        return
    rows = compendium.read_split(release, "train")
    generator = random.Random(seed)
    for indices in compendium.cluster_batches(rows.c090, size, generator):
        yield [compendium.wrap(compendium.train_entry(rows.entries[index], generator), space.bos, space.eos) for index in indices]


@dataclass(frozen=True, slots=True)
class RowStatistics:
    """Per row, the cross entropy summed over its hidden positions, its hits at each top k, and how many positions were hidden."""

    loss: Tensor  # (r,)
    hits: Tensor  # (r, k)
    hidden: Tensor  # (r,)

    def summary(self) -> dict[str, float]:
        """Mean cross entropy and top-k accuracy over every hidden position."""
        total = float(self.hidden.sum())
        return {"loss": float(self.loss.sum()) / total, **{f"top{top}": float(self.hits[:, index].sum()) / total for index, top in enumerate(TOP_K)}}


def fixed_hidden(rows: list[list[int]], space: TokenSpace, size: int, probability: float) -> Iterator[tuple[Tensor, Tensor, Tensor, Tensor]]:
    """Batches of a split with the same hidden tokens at every call: the corrupted ids, mask, original ids and labels of each batch."""
    generator = torch.Generator().manual_seed(0)
    for start in range(0, len(rows), size):
        input_ids, attention_mask = collate(rows[start:start + size], space.pad)  # (b, l), (b, l)
        corrupted, labels = mask_for_mlm(input_ids, attention_mask, space, probability, generator)  # (b, l), (b, l)
        yield corrupted, attention_mask, input_ids, labels


def _by_row(count: int, owner: Tensor, per_position: Tensor, found: Tensor) -> RowStatistics:
    """Sum per-position values into rows: `owner` is the row of each hidden position."""
    # owner: (n,); per_position: (n,); found: (n, k)
    loss = torch.zeros(count, dtype=torch.float64).index_add_(0, owner, per_position.double())  # (b,)
    hits = torch.zeros(count, len(TOP_K), dtype=torch.float64).index_add_(0, owner, found.double())  # (b, k)
    return RowStatistics(loss, hits, torch.bincount(owner, minlength=count).double())


def _join(parts: list[RowStatistics]) -> RowStatistics:
    return RowStatistics(torch.cat([part.loss for part in parts]), torch.cat([part.hits for part in parts]), torch.cat([part.hidden for part in parts]))


@torch.no_grad()
def model_statistics(model: AnnotationTransformer, rows: list[list[int]], space: TokenSpace, size: int, device: torch.device) -> RowStatistics:
    """Each row's loss and hits at the fixed hidden positions of a split."""
    model.eval()
    parts = []
    for corrupted, attention_mask, input_ids, labels in fixed_hidden(rows, space, size, model.config.mlm_mask_probability):
        with torch.autocast(device.type, dtype=torch.bfloat16):
            _, logits, targets = masked_loss(model, corrupted.to(device), attention_mask.to(device), labels.to(device))  # (), (n, v), (n,)
        owner = (labels != IGNORE_INDEX).nonzero()[:, 0]  # (n,)
        per_position = cross_entropy(logits, targets, reduction="none").cpu()  # (n,)
        ranked = logits.topk(max(TOP_K), dim=-1).indices  # (n, k)
        found = torch.stack([(ranked[:, :top] == targets[:, None]).any(dim=1) for top in TOP_K], dim=1).cpu()  # (n, k)
        parts.append(_by_row(input_ids.shape[0], owner, per_position, found))
    model.train()
    return _join(parts)


def prior_statistics(train_rows: list[list[int]], rows: list[list[int]], space: TokenSpace, size: int, probability: float) -> RowStatistics:
    """The train-frequency prior at the same hidden positions: every position gets the train token distribution, smoothed by one count."""
    counts = torch.bincount(torch.tensor([token for row in train_rows for token in row]), minlength=space.terms)[: space.terms].double()  # (t,)
    log_probability = torch.log((counts + 1.0) / (counts.sum() + space.terms))  # (t,)
    ranked = counts.topk(max(TOP_K)).indices  # (k,)
    parts = []
    for _, _, input_ids, labels in fixed_hidden(rows, space, size, probability):
        owner = (labels != IGNORE_INDEX).nonzero()[:, 0]  # (n,)
        targets = labels[labels != IGNORE_INDEX]  # (n,)
        found = torch.stack([torch.isin(targets, ranked[:top]) for top in TOP_K], dim=1)  # (n, k)
        parts.append(_by_row(input_ids.shape[0], owner, -log_probability[targets], found))
    return _join(parts)


def cluster_intervals(statistics: RowStatistics, clusters: Sequence[str]) -> dict[str, dict[str, float]]:
    """Each score over all hidden positions, with the 95 percent interval of resampling whole clusters of rows with replacement."""
    names = {cluster: index for index, cluster in enumerate(sorted(set(clusters)))}
    owner = torch.tensor([names[cluster] for cluster in clusters])  # (r,)
    columns = torch.cat([statistics.loss[:, None], statistics.hits, statistics.hidden[:, None]], dim=1)  # (r, k + 2)
    sums = torch.zeros(len(names), columns.shape[1], dtype=torch.float64).index_add_(0, owner, columns)  # (c, k + 2)
    draws = torch.randint(len(names), (BOOTSTRAP_RESAMPLES, len(names)), generator=torch.Generator().manual_seed(BOOTSTRAP_SEED))  # (B, c)
    totals = sums[draws].sum(dim=1)  # (B, k + 2)
    ratios = totals[:, :-1] / totals[:, -1:]  # (B, k + 1)
    edges = torch.tensor([(1 - INTERVAL_LEVEL) / 2, 1 - (1 - INTERVAL_LEVEL) / 2], dtype=torch.float64)  # (2,)
    low_high = torch.quantile(ratios, edges, dim=0)  # (2, k + 1)
    values = sums[:, :-1].sum(dim=0) / sums[:, -1].sum()  # (k + 1,)
    return {name: {"value": float(values[index]), "low": float(low_high[0, index]), "high": float(low_high[1, index])} for index, name in enumerate(SCORE_NAMES)}


def evaluate(model: AnnotationTransformer, rows: list[list[int]], space: TokenSpace, size: int, device: torch.device) -> dict[str, float]:
    """Loss and top-k accuracy at hidden positions of a split, with the same hidden tokens at every call."""
    return model_statistics(model, rows, space, size, device).summary()


def evaluate_release(arguments: argparse.Namespace, device: torch.device) -> dict[str, object]:
    """Score `best/` once on validation and on test, beside the prior and a random-weight control, and write the evaluation.

    Per-row statistics go to `rows_<split>.parquet` so a later stage can cut the score by any attribute of a row.
    """
    path = arguments.output / EVALUATION_FILE
    if path.exists():
        raise FileExistsError(f"{path} exists: the test split is read once, and this run was already evaluated")
    space = read_token_space(arguments.release)
    train_rows = read_token_lists(arguments.release, "train")
    model = AnnotationTransformer.from_pretrained(arguments.output / "best").to(device)
    set_seed(arguments.seed)
    control = AnnotationTransformer(AnnotationTransformerConfig.from_pretrained(arguments.output / "best")).to(device)  # random weights
    splits: dict[str, object] = {}
    for split in ("validation", "test"):
        frame = read_split(arguments.release, split)
        rows = frame["annotation_tokens"]
        statistics = {
            "model": model_statistics(model, rows, space, arguments.batch_size, device),
            "prior": prior_statistics(train_rows, rows, space, arguments.batch_size, model.config.mlm_mask_probability),
            "random_weights": model_statistics(control, rows, space, arguments.batch_size, device),
        }
        splits[split] = {
            "rows": len(rows), "hidden": int(statistics["model"].hidden.sum()),
            **{name: cluster_intervals(item, frame["cluster_id"]) for name, item in statistics.items()},
        }
        pq.write_table(pa.table({
            "protein_id": frame["protein_id"], "cluster_id": frame["cluster_id"], "hidden": statistics["model"].hidden.tolist(),
            "loss": statistics["model"].loss.tolist(), "top1": statistics["model"].hits[:, 0].tolist(), "top5": statistics["model"].hits[:, 1].tolist(),
        }), arguments.output / f"rows_{split}.parquet", compression="zstd")
    evaluation = {
        "checkpoint": "best", "selection_split": "validation",
        "interval": f"{INTERVAL_LEVEL:.0%} cluster bootstrap, {BOOTSTRAP_RESAMPLES} resamples, seed {BOOTSTRAP_SEED}", "splits": splits,
    }
    path.write_text(json.dumps(evaluation, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return evaluation


def summarize_evaluation(evaluation: dict[str, object], best_loss: float, best_step: int) -> dict[str, float]:
    """The flat scores of a run: the selection step and loss, then the best checkpoint's validation and test scores and the prior's."""
    splits = evaluation["splits"]
    return {
        "best_validation_loss": best_loss, "best_step": best_step,
        **{f"{split}_{name}": splits[split]["model"][name]["value"] for split in ("validation", "test") for name in SCORE_NAMES},
        **{f"{split}_prior_{name}": splits[split]["prior"][name]["value"] for split in ("validation", "test") for name in SCORE_NAMES},
    }


def parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--experiment", required=True, help="the experiment id, which is the W&B group")
    parser.add_argument("--preset", default="at_base")
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--steps", type=int, default=20_000)
    parser.add_argument("--warmup", type=int, default=500)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--min-lr-ratio", type=float, default=0.1)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument("--max-grad-norm", type=float, default=1.0)
    parser.add_argument("--eval-every", type=int, default=500)
    parser.add_argument("--patience", type=int, default=10, help="evaluations without a better validation loss before stopping")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--pilot", action="store_true", help="time 20 steps and stop")
    parser.add_argument("--wandb-project", default="annotation-transformer")
    parser.add_argument("--no-wandb", action="store_true")
    parser.add_argument("--hub-repo", default=None, help="a Hub model repository to push to, always private")
    parser.add_argument("--evaluate-only", action="store_true", help="score an existing best/ once on validation and test; for a run made before the default did")
    parser.add_argument("--push-only", action="store_true", help="push best/ and the card files of the output directory")
    return parser.parse_args(argv)


def train(arguments: argparse.Namespace) -> dict[str, float]:
    """Train on the release's train split, keep the best validation checkpoint, and return the final scores."""
    set_seed(arguments.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    space = read_token_space(arguments.release)
    validation_rows = read_split(arguments.release, "validation")["annotation_tokens"]
    config = AnnotationTransformerConfig.from_preset(arguments.preset, vocab_size=space.size, pad_token_id=space.pad, mask_token_id=space.mask,
                                                     bos_token_id=space.bos, eos_token_id=space.eos)
    model = AnnotationTransformer(config).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=arguments.lr, weight_decay=arguments.weight_decay, betas=(0.9, 0.98))
    schedule = Schedule(arguments.warmup, arguments.steps, arguments.min_lr_ratio)
    generator = torch.Generator().manual_seed(arguments.seed)
    arguments.output.mkdir(parents=True, exist_ok=True)
    run = None if arguments.no_wandb or arguments.pilot else Run(
        arguments.output, {key: str(value) for key, value in vars(arguments).items()} | {"experiment_id": arguments.experiment, "vocabulary": space.size},
        project=arguments.wandb_project, revision=revision_of(Path(__file__)), group=arguments.experiment, job_type="train",
    )
    pilot = Pilot(total_steps=arguments.steps, items=lambda batch: len(batch), item_unit="entries", stop=arguments.pilot, receipt=arguments.output / "pilot.json")
    best, best_step, stale, scores = math.inf, 0, 0, {}
    model.train()
    stream = pilot.watch(training_batches(arguments.release, space, arguments.batch_size, arguments.seed))
    for step, rows in enumerate(tqdm(stream, total=arguments.steps, desc="AT pretraining", mininterval=30)):
        for group in optimizer.param_groups:
            group["lr"] = arguments.lr * schedule.factor(step)
        input_ids, attention_mask = collate(rows, space.pad)  # (b, l), (b, l)
        corrupted, labels = mask_for_mlm(input_ids, attention_mask, space, config.mlm_mask_probability, generator)  # (b, l), (b, l)
        with torch.autocast(device.type, dtype=torch.bfloat16):
            loss, _, _ = masked_loss(model, corrupted.to(device), attention_mask.to(device), labels.to(device))  # (), (n, v), (n,)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        norm = clip_grad_norm(model, arguments.max_grad_norm)
        optimizer.step()
        if run is not None and step % 50 == 0:
            run.log({"train/loss": float(loss), "train/grad_norm": float(norm), "train/lr": optimizer.param_groups[0]["lr"]}, step)
        if (step + 1) % arguments.eval_every == 0 or step + 1 == arguments.steps:
            scores = evaluate(model, validation_rows, space, arguments.batch_size, device)
            if run is not None:
                run.log({f"validation/{name}": value for name, value in scores.items()}, step)
            if scores["loss"] < best:
                best, best_step, stale = scores["loss"], step + 1, 0
                model.save_pretrained(arguments.output / "best")
            else:
                stale += 1
            if stale >= arguments.patience or step + 1 >= arguments.steps:
                break
    if arguments.pilot:
        return scores
    model.save_pretrained(arguments.output / "last")
    del model
    evaluation = evaluate_release(arguments, device)
    summary = summarize_evaluation(evaluation, best, best_step)
    (arguments.output / "scores.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    if run is not None:
        run.finish(summary=summary)
    if arguments.hub_repo:
        push_private(arguments.output, arguments.hub_repo)
    return summary


def evaluate_existing(arguments: argparse.Namespace) -> dict[str, float]:
    """Score the `best/` of a finished run once, write `scores.json`, and log the scores as an evaluation run of the same group.

    The best step and loss come from the run's own `history.jsonl`, since the checkpoint does not record them.
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    evaluation = evaluate_release(arguments, device)
    history = [json.loads(line) for line in (arguments.output / "history.jsonl").read_text(encoding="utf-8").splitlines()]
    best = min((entry for entry in history if "validation/loss" in entry), key=lambda entry: entry["validation/loss"])
    summary = summarize_evaluation(evaluation, best["validation/loss"], best["step"] + 1)
    (arguments.output / "scores.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    if not arguments.no_wandb:
        run = Run(
            arguments.output / "evaluation", {key: str(value) for key, value in vars(arguments).items()} | {"experiment_id": arguments.experiment},
            project=arguments.wandb_project, revision=revision_of(Path(__file__)), group=arguments.experiment, job_type="evaluate",
        )
        run.finish(summary=summary)
    return summary


def push_private(directory: Path, repository: str) -> str:
    """Make the repository's root hold the best checkpoint of `directory` and its card files, in one commit; created private.

    Files the new root does not hold are deleted in the same commit, so an earlier revision keeps what it had and the head holds one model.
    """
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi

    api = HfApi()
    api.create_repo(repository, repo_type="model", private=True, exist_ok=True)
    files = {path.name: path for path in sorted((directory / "best").iterdir()) if path.is_file()}
    files |= {name: directory / name for name in CARD_FILES if (directory / name).is_file()}
    remote = set(api.list_repo_files(repository, repo_type="model"))
    operations = [CommitOperationAdd(path_in_repo=name, path_or_fileobj=str(path)) for name, path in files.items()]
    operations += [CommitOperationDelete(path_in_repo=name) for name in sorted(remote - files.keys() - {".gitattributes"})]
    commit = api.create_commit(repository, operations, repo_type="model", commit_message="Best checkpoint by validation loss, scored once on test")
    return commit.oid


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    if arguments.push_only:
        print(push_private(arguments.output, arguments.hub_repo))
        return 0
    print(json.dumps(evaluate_existing(arguments) if arguments.evaluate_only else train(arguments), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
