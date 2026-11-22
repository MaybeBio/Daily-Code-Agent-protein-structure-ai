"""E16b, exploratory: a resized ESMC-600 trained against the intact one.

The student is E16a's fixed set of units at ESMC-300's size (`pruning.resized`), every parameter trainable, in float32
under bf16 autocast; the teacher is the intact ESMC-600. A step reads proteins of about `TOKENS` padded tokens with a
fresh 15% of each protein's residues masked, and descends the sum of three terms of equal weight:

- `ce`: cross-entropy to the true residue at the masked residues;
- `kl`: the KL divergence from the teacher's distribution to the student's there;
- `stream`: the squared error of the stream leaving each block, over every token, divided by the teacher stream's sum
  of squares, averaged over the blocks. It needs the two models to share their width, so the control leaves it out.

The control trains ESMC-300 itself on the first two terms for the same steps, which separates what pruning gives from
what any model of that size gains by being distilled from ESMC-600 on these proteins.

AdamW with a linear warm-up and a cosine decay to a tenth of the peak. The state kept is the one of lowest masked loss
on validation proteins, read every `VALIDATE_EVERY` steps and at the end. The loop is this stage's own, for one
exploratory run; a pruning project would train through `foundry.training.trainer.Trainer`.

Symbols: b proteins of a batch; l token columns; d model width; n blocks; s masked residues; v tokens of the
vocabulary; p proteins.
"""

from __future__ import annotations

import math
import time
import numpy as np
import torch

from collections.abc import Callable, Sequence
from pathlib import Path
from safetensors.torch import save_file
from torch import Tensor, nn
from torch.nn import functional

from .ablation import column_mask
from .atlas import encode_batch, length_batches
from .causal import transformer_blocks
from .sparsify import masked_distributions, readout


TOKENS = 16_384
MASK_SHARE = 0.15
LEARNING_RATE = 3e-5
WEIGHT_DECAY = 0.01
WARMUP_STEPS = 100
FLOOR = 0.1  # the share of the peak learning rate the cosine ends at
CLIP = 1.0
VALIDATE_EVERY = 250
LOG_EVERY = 50
CHUNK = 4_096  # proteins sorted by length together, so that a batch pads little
PASSES = 3
VALIDATION_PROTEINS = 500
PILOT_STEPS = 40
SEED = 24895


class LeavingStreams:
    """The stream leaving each block in a model's latest forward passes, kept only while `on`."""

    def __init__(self, model: nn.Module) -> None:
        self.on = False
        self.streams: list[Tensor] = []
        self.handles = [layer.register_forward_hook(self._keep) for layer in transformer_blocks(model)]

    def _keep(self, module: nn.Module, args: tuple[object, ...], output: object) -> None:
        if self.on:
            self.streams.append(output[0] if isinstance(output, tuple) else output)  # (b, l, d)

    def take(self) -> list[Tensor]:
        streams, self.streams = self.streams, []
        return streams  # n of (b, l, d)

    def remove(self) -> None:
        for handle in self.handles:
            handle.remove()


def pass_batches(lengths: np.ndarray, generator: np.random.Generator, *, tokens: int = TOKENS, chunk: int = CHUNK) -> list[np.ndarray]:
    """One pass over the proteins in a random order, as batches of proteins of similar length that pad to about
    `tokens` tokens, the batches in a random order too."""
    # lengths: (p,)
    order = generator.permutation(len(lengths))  # (p,)
    groups = []
    for start in range(0, len(order), chunk):
        rows = order[start:start + chunk]
        rows = rows[np.argsort(lengths[rows], kind="stable")]
        groups.extend(rows[batch] for batch in length_batches(lengths[rows], tokens))
    return [groups[index] for index in generator.permutation(len(groups))]  # (b,) protein rows for each batch


def learning_rate(step: int, steps: int, peak: float, *, warmup: int = WARMUP_STEPS, floor: float = FLOOR) -> float:
    """The rate at 0-based `step`: a linear rise over `warmup` steps, then a cosine from the peak to `floor` of it."""
    if step < warmup:
        return peak * (step + 1) / warmup
    progress = (step - warmup) / max(1, steps - 1 - warmup)
    return peak * (floor + (1.0 - floor) * 0.5 * (1.0 + math.cos(math.pi * min(progress, 1.0))))


def heal_terms(student_logits: Tensor, teacher_logits: Tensor, truth: Tensor, student_streams: Sequence[Tensor],
               teacher_streams: Sequence[Tensor], tokens: Tensor) -> dict[str, Tensor]:
    """The terms of the loss; `stream` only when streams are given."""
    # student_logits, teacher_logits: (s, v); truth: (s,); student_streams, teacher_streams: (b, l, d) for each of n
    # blocks; tokens: (b, l), true at every token that is not padding
    log_student = functional.log_softmax(student_logits.float(), dim=-1)  # (s, v)
    teacher = functional.softmax(teacher_logits.float(), dim=-1)  # (s, v)
    terms = {"ce": functional.nll_loss(log_student, truth),
             "kl": (teacher * (teacher.clamp_min(1e-12).log() - log_student)).sum(dim=-1).mean()}
    if student_streams:
        weight = tokens.unsqueeze(-1).float()  # (b, l, 1)
        errors = []
        for ours, theirs in zip(student_streams, teacher_streams, strict=True):
            theirs = theirs.float()  # (b, l, d)
            errors.append(((ours.float() - theirs).pow(2) * weight).sum() / (theirs.pow(2) * weight).sum())
        terms["stream"] = torch.stack(errors).mean()  # ()
    return terms  # () each


def masked_read(model: nn.Module, sequences: Sequence[str], chosen: Sequence[np.ndarray], clean: Tensor, device: torch.device, *,
                token_budget: int) -> dict[str, float]:
    """Loss, accuracy and KL from `clean` at the chosen residues, under the autocast the training runs in."""
    # chosen: (s_protein,) 0-based residues for each protein; clean: (s, v)
    with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
        log_probs, truth = masked_distributions(model, list(sequences), chosen, device, token_budget=token_budget)
    return readout(log_probs, truth, clean)


def heal(student: nn.Module, teacher: nn.Module, train: Sequence[str], validation: Sequence[str],
         validation_chosen: Sequence[np.ndarray], device: torch.device, output: Path, *, steps: int, peak: float = LEARNING_RATE,
         match_streams: bool = True, tokens: int = TOKENS, validate_every: int = VALIDATE_EVERY, log_every: int = LOG_EVERY,
         seed: int = SEED, record: Callable[[dict[str, float], int], None] = lambda metrics, step: None,
         log: Callable[[str], None] = print) -> list[dict[str, float]]:
    """Train `student` against `teacher` for `steps` steps and leave the state of lowest validation loss at
    `output/best.safetensors`. Returns one row per validation read. `record` receives the logged metrics and the
    step."""
    # validation_chosen: (s_protein,) 0-based residues for each validation protein
    generator = np.random.default_rng(seed)
    torch.manual_seed(seed)
    tokenizer = teacher.tokenizer
    lengths = np.array([len(sequence) for sequence in train], dtype=np.int64)  # (p,)
    clean, _ = masked_distributions(teacher, list(validation), validation_chosen, device, token_budget=2 * tokens)  # (s, v)
    optimizer = torch.optim.AdamW(student.parameters(), lr=peak, weight_decay=WEIGHT_DECAY)
    ours, theirs = (LeavingStreams(student), LeavingStreams(teacher)) if match_streams else (None, None)
    history, best, queue, window = [], math.inf, [], []
    started = time.perf_counter()
    try:
        for step in range(steps):
            if not queue:
                queue = pass_batches(lengths, generator, tokens=tokens)
            rows = queue.pop()
            sequences = [train[row] for row in rows]
            input_ids, attention_mask, _ = encode_batch(tokenizer, sequences, device)  # (b, l) each
            residues = [generator.choice(len(sequence), size=max(1, int(round(MASK_SHARE * len(sequence)))), replace=False)
                        for sequence in sequences]
            positions = column_mask(residues, tuple(input_ids.shape)).to(device)  # (b, l)
            masked = input_ids.masked_fill(positions, tokenizer.mask_token_id)  # (b, l)
            if match_streams:
                ours.on = theirs.on = True
            with torch.no_grad():
                teacher_logits = teacher(input_ids=masked, attention_mask=attention_mask).logits[positions]  # (s, v)
            student.train()
            with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                student_logits = student(input_ids=masked, attention_mask=attention_mask).logits[positions]  # (s, v)
            if match_streams:
                ours.on = theirs.on = False
            terms = heal_terms(student_logits, teacher_logits, input_ids[positions], ours.take() if match_streams else (),
                               theirs.take() if match_streams else (), attention_mask.bool())
            loss = torch.stack(list(terms.values())).sum()
            if not bool(torch.isfinite(loss)):
                raise RuntimeError(f"The loss is not finite at step {step}: { {name: float(term.detach()) for name, term in terms.items()} }")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            norm = float(nn.utils.clip_grad_norm_(student.parameters(), CLIP))
            for group in optimizer.param_groups:
                group["lr"] = learning_rate(step, steps, peak)
            optimizer.step()
            window.append({"train/loss": float(loss.detach()), "train/gradient_norm": norm,
                           **{f"train/{name}": float(term.detach()) for name, term in terms.items()}})
            if (step + 1) % log_every == 0 or step + 1 == steps:
                metrics = {name: float(np.mean([row[name] for row in window])) for name in window[0]}
                metrics["train/learning_rate"] = learning_rate(step, steps, peak)
                metrics["train/seconds_a_step"] = (time.perf_counter() - started) / (step + 1)
                record(metrics, step + 1)
                log(f"heal step {step + 1}/{steps}: " + ", ".join(f"{name.split('/')[1]} {value:.4f}" for name, value in metrics.items()))
                window = []
            if (step + 1) % validate_every == 0 or step + 1 == steps:
                student.eval()
                read = masked_read(student, validation, validation_chosen, clean, device, token_budget=2 * tokens)
                kept = read["loss"] < best
                if kept:
                    best = read["loss"]
                    save_file({name: value.detach().cpu() for name, value in student.state_dict().items()},
                              str(output / "best.safetensors"), metadata={"step": str(step + 1)})
                history.append({"step": step + 1, **read, "kept": kept, "seconds": time.perf_counter() - started})
                record({f"val/{name}": value for name, value in read.items()}, step + 1)
                log(f"heal step {step + 1}: validation loss {read['loss']:.4f}, accuracy {read['accuracy']:.4f}, KL {read['kl']:.4f}"
                    + (", kept" if kept else ""))
    finally:
        if match_streams:
            ours.remove()
            theirs.remove()
    return history
