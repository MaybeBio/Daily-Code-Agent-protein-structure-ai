"""ProstT5's 3Di prediction from amino acids (Heinzinger et al. 2024), in process beside other models on one GPU.

The authors' `scripts/predict_3Di_encoderOnly.py` (code commit 3f6c0666) step for step in half precision, as
alignment_atlas's `prostt5_states.py` runs it over whole databases in ProstT5's own image: the `<AA2fold>` prefix,
residues outside the 20 as X, the T5 encoder, EOS and padding zeroed, the prefix row dropped, the authors' CNN and the
most likely state per residue. The weights are `Rostlab/ProstT5` at `REVISION` cast to half precision, the copy every
stored ProstT5 state in this tree came from, and the CNN is the authors' checkpoint at `CNN_URL`, checked by sha256.

As in the authors' script, the CNN's second layer reads its first layer's output over padding rows after a sequence,
so a sequence's last two states can depend on the longest sequence batched with it; `predict` batches longest first.

Symbols: b sequences, l tokens (the prefix, the residues, EOS, padding), f ProstT5's width (1024).
"""

from __future__ import annotations

import hashlib
import numpy as np
import torch

from pathlib import Path
from torch import nn


REPOSITORY = "Rostlab/ProstT5"
REVISION = "d7d097d5bf9a993ab8f68488b4681d6ca70db9e5"  # alignment_atlas's pin (2026-10-17_external_baselines_scope40)
CNN_URL = "https://github.com/mheinzinger/ProstT5/raw/3f6c0666ac61d1025ce9473e34d3f67fc893a589/cnn_chkpnt/model.pt"
CNN_SHA256 = "d2cb4150884de095dac3de81b8fe7842ab1265de41dd5e8c9970879a71e62f3e"
FILES = ("config.json", "pytorch_model.bin", "spiece.model", "special_tokens_map.json", "tokenizer_config.json")
STATES = "ACDEFGHIKLMNPQRSTVWY"  # the CNN's 20 outputs in order: Foldseek's 3Di letters
STANDARD = frozenset(STATES)  # the amino acids kept as they are; any other letter becomes X
PREFIX = "<AA2fold>"


class CNN(nn.Module):
    """The authors' 3Di head over ProstT5's per-residue encodings: (b, l, f) to (b, 20, l); its keys match their checkpoint."""

    def __init__(self) -> None:
        super().__init__()
        self.classifier = nn.Sequential(nn.Conv2d(1024, 32, kernel_size=(7, 1), padding=(3, 0)), nn.ReLU(), nn.Dropout(0.0),
                                        nn.Conv2d(32, 20, kernel_size=(7, 1), padding=(3, 0)))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (b, l, f)
        return self.classifier(x.permute(0, 2, 1).unsqueeze(dim=-1)).squeeze(dim=-1)  # (b, 20, l)


class ProstT5States:
    """ProstT5's encoder and the CNN resident on `device`, from a model folder holding `FILES` and the CNN file."""

    def __init__(self, folder: Path, cnn: Path, device: torch.device | str) -> None:
        from transformers import T5EncoderModel, T5Tokenizer

        digest = hashlib.sha256(cnn.read_bytes()).hexdigest()
        if digest != CNN_SHA256:
            raise ValueError(f"{cnn} has sha256 {digest}, not the authors' CNN {CNN_SHA256}.")
        self.device = torch.device(device)
        self.tokenizer = T5Tokenizer.from_pretrained(folder, do_lower_case=False)
        self.encoder = T5EncoderModel.from_pretrained(folder, dtype=torch.float16).to(self.device).eval()
        head = CNN()
        head.load_state_dict(torch.load(cnn, map_location="cpu", weights_only=True)["state_dict"])
        self.head = head.half().to(self.device).eval()

    @torch.no_grad()
    def predict(self, sequences: list[str], max_residues: int = 16000) -> list[str]:
        """The most likely 3Di state of every residue of each sequence, batched longest first up to `max_residues`."""
        lengths = np.array([len(sequence) for sequence in sequences])  # (n)
        out: list[str] = [""] * len(sequences)
        batch: list[int] = []
        for row in [*np.argsort(-lengths, kind="stable").tolist(), None]:
            if batch and (row is None or int(lengths[batch].sum()) + int(lengths[row]) > max_residues):
                for index, states in zip(batch, self._batch([sequences[index] for index in batch]), strict=True):
                    out[index] = states
                batch = []
            if row is not None:
                batch.append(row)
        return out

    def _batch(self, sequences: list[str]) -> list[str]:
        texts = [PREFIX + " " + " ".join(a if a in STANDARD else "X" for a in sequence) for sequence in sequences]
        tokens = self.tokenizer(texts, add_special_tokens=True, padding="longest", return_tensors="pt").to(self.device)
        lengths = torch.tensor([len(sequence) for sequence in sequences], device=self.device)  # (b)
        if not torch.equal(tokens.attention_mask.sum(dim=1), lengths + 2):  # the prefix, one token per residue, EOS
            raise ValueError("ProstT5's tokenizer did not give one token per residue.")
        hidden = self.encoder(tokens.input_ids, attention_mask=tokens.attention_mask).last_hidden_state  # (b, l, f)
        mask = tokens.attention_mask.clone()  # (b, l)
        mask[torch.arange(len(sequences), device=self.device), lengths + 1] = 0  # EOS
        hidden = (hidden * mask.unsqueeze(dim=-1))[:, 1:]  # padding zeroed, the prefix row dropped: (b, l - 1, f)
        best = self.head(hidden).argmax(dim=1).cpu().numpy()  # (b, l - 1)
        return ["".join(STATES[state] for state in row[: len(sequence)]) for row, sequence in zip(best, sequences, strict=True)]
