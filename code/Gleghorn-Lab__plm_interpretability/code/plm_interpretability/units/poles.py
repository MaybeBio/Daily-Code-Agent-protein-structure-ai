"""Neuron poles: each gated feed-forward unit read as two signed poles, with the gate-closed leak kept apart.

ESMC's feed-forward branch forms z = SiLU(g) * u from a gate g and an up projection u (FastPLMs `SwiGLU` applies SiLU
to the first half of the projection). With the gate open (g > 0) the sign of u selects the positive or the negative
pole. With the gate closed, SiLU's negative lobe passes a small, sign-flipped copy of u, the double-negative leak that
Cammarata (Goodfire, 2026) found at the top of about 4% of a language model's neurons; it is kept as two leak poles and
never folded into the main ones. Every pole activation is nonnegative, and the four poles of a unit sum back to z with
signs (`SwigluPoles.product`), so no activity is lost.

Symbols: r residues; f units; w the width of any signed state. Pole matrices put a unit's positive pole in column j
and its negative pole in column f + j.
"""

from __future__ import annotations

import torch

from dataclasses import dataclass
from torch import Tensor
from torch.nn import functional


# min over x of x * sigmoid(x), reached at x of about -1.2785: the largest a gate-closed unit can scale |u| by.
SILU_MINIMUM = -0.2784645427610738


@dataclass(frozen=True)
class SwigluPoles:
    """The four nonnegative poles of every unit of one SwiGLU block at every residue."""

    positive: Tensor  # (r, f), z where g > 0 and u > 0
    negative: Tensor  # (r, f), -z where g > 0 and u < 0
    leak_positive: Tensor  # (r, f), z where g <= 0 and u < 0 (positive output, sign-flipped from the negative pole)
    leak_negative: Tensor  # (r, f), -z where g <= 0 and u > 0

    def main(self) -> Tensor:
        """The labeled units: positive poles in columns 0..f-1, negative poles in f..2f-1."""
        return torch.cat((self.positive, self.negative), dim=-1)  # (r, 2f)

    def leaks(self) -> Tensor:
        """The gate-closed regime, in the same column layout as `main`."""
        return torch.cat((self.leak_positive, self.leak_negative), dim=-1)  # (r, 2f)

    def product(self) -> Tensor:
        """z rebuilt from its poles; equals SiLU(g) * u exactly."""
        return self.positive - self.negative + self.leak_positive - self.leak_negative  # (r, f)


def swiglu_poles(gate: Tensor, up: Tensor) -> SwigluPoles:
    """Split z = SiLU(gate) * up into its gate-tagged poles, computed in float32 whatever the inputs' precision.

    BF16 gates and up projections have few distinct values; their product in float32 has far fewer ties, which the
    firing-rate thresholds need.
    """
    # gate, up: (r, f)
    if gate.shape != up.shape:
        raise ValueError(f"Gate {tuple(gate.shape)} and up projection {tuple(up.shape)} differ in shape.")
    gate = gate.float()  # (r, f)
    up = up.float()  # (r, f)
    product = functional.silu(gate) * up  # (r, f)
    zero = product.new_zeros(())  # ()
    is_open = gate > 0  # (r, f)
    return SwigluPoles(
        positive=torch.where(is_open & (up > 0), product, zero),  # (r, f)
        negative=torch.where(is_open & (up < 0), -product, zero),  # (r, f)
        leak_positive=torch.where(~is_open & (up < 0), product, zero),  # (r, f)
        leak_negative=torch.where(~is_open & (up > 0), -product, zero),  # (r, f)
    )


def sign_poles(state: Tensor) -> Tensor:
    """Any signed state read as two poles by sign alone: positive parts, then negative parts.

    The residual-stream basis, rotated units, ESM-2's MLP pre-activations, the sign-only sensitivity of SwiGLU units and
    the gate alone (its open pole g > 0 and closed pole g < 0) all use this reading.
    """
    # state: (r, w)
    state = state.float()  # (r, w)
    return torch.cat((torch.relu(state), torch.relu(-state)), dim=-1)  # (r, 2w)


def pole_unit(column: int, width: int) -> tuple[int, str]:
    """The unit and sign of a pole column in the `SwigluPoles.main` or `sign_poles` layout."""
    if not 0 <= column < 2 * width:
        raise ValueError(f"Pole column {column} is outside 0..{2 * width - 1} for width {width}.")
    return (column, "positive") if column < width else (column - width, "negative")
