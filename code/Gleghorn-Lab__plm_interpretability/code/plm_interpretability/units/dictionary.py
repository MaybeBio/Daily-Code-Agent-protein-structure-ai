"""The dictionary test: how much of an SAE's activity is a near-copy of one native pole.

Cammarata (Goodfire, 2026) reports that 88% of the activity of an SAE on a vision model's last layer sat on latents that
near-copy single neurons, and that removing the directions that match no neuron left accuracy unchanged. Here an SAE
latent copies a pole when its activation, over a sample of residues, correlates with that one pole's activation at or
above a threshold (0.7 primary; 0.5 and 0.9 secondary), and the share of the SAE's total activation carried by such
latents is reported, beside the same share against the poles of a Haar-rotated basis as its chance level. For an SAE on
a block's feed-forward write, a copying latent's decoder direction should also lie along its pole's write vector: +w_j
for a positive pole, -w_j for a negative one. Biohub's SAEs reconstruct residue states centered and scaled per residue,
so both directions are compared after removing their mean across dimensions.

Symbols: r residues; m latents; p poles; k codes per residue; f units; d model width.
"""

from __future__ import annotations

import torch

from dataclasses import dataclass
from torch import Tensor


THRESHOLDS = (0.5, 0.7, 0.9)


class CorrelationAccumulator:
    """Running sums for the Pearson correlation of every latent with every pole over all residues it is given."""

    def __init__(self, n_latents: int, n_poles: int, device: str | torch.device = "cpu", dtype: torch.dtype = torch.float64) -> None:
        self.device, self.dtype = torch.device(device), dtype
        self.count = 0
        self.latent_sum = torch.zeros(n_latents, dtype=dtype, device=self.device)  # (m,)
        self.latent_square = torch.zeros(n_latents, dtype=dtype, device=self.device)  # (m,)
        self.pole_sum = torch.zeros(n_poles, dtype=dtype, device=self.device)  # (p,)
        self.pole_square = torch.zeros(n_poles, dtype=dtype, device=self.device)  # (p,)
        self.cross = torch.zeros((n_latents, n_poles), dtype=dtype, device=self.device)  # (m, p)

    def _add_poles(self, poles: Tensor) -> Tensor:
        # poles: (r, p)
        poles = poles.to(self.device, self.dtype)  # (r, p)
        self.count += int(poles.shape[0])
        self.pole_sum += poles.sum(dim=0)
        self.pole_square += (poles**2).sum(dim=0)
        return poles  # (r, p)

    def update(self, latents: Tensor, poles: Tensor) -> None:
        """Add a batch of residues: the dictionary's activations and the poles' at the same residues."""
        # latents: (r, m), dense or sparse COO; poles: (r, p)
        if latents.shape[0] != poles.shape[0]:
            raise ValueError("Latents and poles must cover the same residues.")
        dense = latents.to_dense() if latents.is_sparse else latents
        dense = dense.to(self.device, self.dtype)  # (r, m)
        poles = self._add_poles(poles)  # (r, p)
        self.latent_sum += dense.sum(dim=0)
        self.latent_square += (dense**2).sum(dim=0)
        self.cross += dense.T @ poles  # (m, p)

    def update_codes(self, indices: Tensor, values: Tensor, poles: Tensor) -> None:
        """Add a batch of residues given as TopK codes, never forming the dense activations: each of the k slots adds its
        residues' pole rows, scaled by the slot's value, to the rows of the latents it names. A zero-valued slot adds
        nothing, whatever index it carries."""
        # indices, values: (r, k); poles: (r, p)
        if indices.shape != values.shape or indices.shape[0] != poles.shape[0]:
            raise ValueError("Codes and poles must cover the same residues.")
        indices = indices.to(self.device)  # (r, k)
        values = values.to(self.device, self.dtype)  # (r, k)
        poles = self._add_poles(poles)  # (r, p)
        self.latent_sum.index_add_(0, indices.reshape(-1), values.reshape(-1))
        self.latent_square.index_add_(0, indices.reshape(-1), values.reshape(-1) ** 2)
        for slot in range(indices.shape[1]):
            self.cross.index_add_(0, indices[:, slot], values[:, slot, None] * poles)

    def absorb(self, other: CorrelationAccumulator) -> None:
        """Add another accumulator's residues to this one, as if it had been given them."""
        if other.cross.shape != self.cross.shape:
            raise ValueError("Only accumulators of the same latents and poles can be joined.")
        self.count += other.count
        for name in ("latent_sum", "latent_square", "pole_sum", "pole_square", "cross"):
            getattr(self, name).add_(getattr(other, name).to(self.device, self.dtype))

    def moments(self, rows: slice | Tensor | None = None) -> tuple[Tensor, Tensor, Tensor]:
        """Covariance of the latents in `rows` (all by default) with each pole, and the standard deviations of those
        latents and of the poles, in float64 whatever precision the sums were kept in."""
        # rows: (m_rows,) latent indices, or a slice of them
        n = float(self.count)
        if n < 2:
            raise ValueError("Correlations need at least two residues.")
        rows = slice(None) if rows is None else rows
        latent_sum = self.latent_sum[rows].double()  # (m_rows,)
        pole_sum = self.pole_sum.double()  # (p,)
        covariance = self.cross[rows].double() / n - torch.outer(latent_sum, pole_sum) / n**2  # (m_rows, p)
        latent_sd = (self.latent_square[rows].double() / n - (latent_sum / n) ** 2).clamp(min=0).sqrt()  # (m_rows,)
        pole_sd = (self.pole_square.double() / n - (pole_sum / n) ** 2).clamp(min=0).sqrt()  # (p,)
        return covariance, latent_sd, pole_sd  # (m_rows, p), (m_rows,), (p,)

    def correlations(self, rows: slice | Tensor | None = None) -> Tensor:
        """Pearson correlation of the latents in `rows` (all by default) with each pole; zero where either never varies."""
        # rows: (m_rows,) latent indices, or a slice of them
        covariance, latent_sd, pole_sd = self.moments(rows)  # (m_rows, p), (m_rows,), (p,)
        scale = torch.outer(latent_sd, pole_sd)  # (m_rows, p)
        return torch.where(scale > 0, covariance / scale, torch.zeros_like(covariance))  # (m_rows, p)

    def best(self, chunk: int = 4096) -> tuple[Tensor, Tensor]:
        """Each latent's largest correlation with any pole, and that pole, `chunk` latents at a time so the full
        correlation matrix is never formed."""
        values, poles = [], []
        for start in range(0, self.cross.shape[0], chunk):
            value, pole = self.correlations(slice(start, start + chunk)).max(dim=1)  # (c,), (c,)
            values.append(value)
            poles.append(pole)
        return torch.cat(values), torch.cat(poles)  # (m,), (m,)

    @property
    def mass(self) -> Tensor:
        """Each latent's total activation, the weight of its share."""
        return self.latent_sum  # (m,)


@dataclass(frozen=True)
class CopyReport:
    best_pole: Tensor  # (m,), the pole each latent correlates with most
    best_correlation: Tensor  # (m,)
    shares: dict[float, float]  # threshold -> share of total activation on latents at or above it


def copy_report(accumulator: CorrelationAccumulator, thresholds: tuple[float, ...] = THRESHOLDS) -> CopyReport:
    """The share of the dictionary's activity on latents that copy one pole, at each threshold."""
    best_correlation, best_pole = accumulator.best()  # (m,), (m,)
    mass = accumulator.mass  # (m,)
    total = float(mass.sum())
    if total <= 0:
        raise ValueError("The dictionary never fired on the sampled residues.")
    shares = {threshold: float(mass[best_correlation >= threshold].sum()) / total for threshold in thresholds}
    return CopyReport(best_pole=best_pole, best_correlation=best_correlation, shares=shares)


def matched_write_cosines(decoder: Tensor, write: Tensor, poles: Tensor, *, centered: bool = True, chunk: int = 16_384) -> Tensor:
    """Cosine of each latent's decoder direction with the signed write direction of one pole each, given in the
    `poles.SwigluPoles.main` layout: +w_j for pole j, -w_j for pole f + j. `centered` first removes each vector's mean
    across dimensions."""
    # decoder: (m, d); write: (d, f), the down projection's columns; poles: (m,) pole columns in 0..2f-1
    width = write.shape[1]
    if decoder.shape[0] != poles.shape[0] or decoder.shape[1] != write.shape[0]:
        raise ValueError(f"Decoder {tuple(decoder.shape)}, write {tuple(write.shape)} and poles {tuple(poles.shape)} disagree.")
    if bool(((poles < 0) | (poles >= 2 * width)).any()):
        raise ValueError(f"Pole columns must lie in 0..{2 * width - 1}.")
    write = write.detach().double()  # (d, f)
    poles = poles.to(write.device)  # (m,)
    cosines = []
    for start in range(0, decoder.shape[0], chunk):
        rows = decoder[start:start + chunk].detach().to(write.device, torch.float64)  # (c, d)
        chosen = poles[start:start + chunk]  # (c,)
        directions = write[:, chosen % width].T  # (c, d)
        if centered:
            rows = rows - rows.mean(dim=1, keepdim=True)  # (c, d)
            directions = directions - directions.mean(dim=1, keepdim=True)  # (c, d)
        signs = torch.where(chosen < width, 1.0, -1.0).to(torch.float64)  # (c,)
        cosines.append(signs * torch.nn.functional.cosine_similarity(rows, directions, dim=1))  # (c,)
    return torch.cat(cosines)  # (m,)
