"""Node and edge features.

Nothing here may depend on which amino acid a residue is. Only backbone atoms are read,
never side chains, since side chain shape would give away the identity and let arm C solve
its task without learning anything. tests/test_graph.py enforces this.

Everything is an angle or a distance, so the features do not change when a protein is
rotated or shifted.
"""
from collections.abc import Sequence

import torch
from torch import Tensor

# Backbone atom order used by megascale.read_pdb -> coords[N, 4, 3]
N_ATOM, CA_ATOM, C_ATOM, O_ATOM = 0, 1, 2, 3

NODE_FEAT_DIM = 10          # 3 torsions + 2 virtual angles, each as (sin, cos)
RBF_DIM = 16
SEP_BINS = (1, 2, 3, 4, 8, 16, 32)       # upper edges; 8 buckets with the final catch-all
EDGE_FEAT_DIM = RBF_DIM + len(SEP_BINS) + 1


def dihedral(p0: Tensor, p1: Tensor, p2: Tensor, p3: Tensor) -> Tensor:
    """Torsion angle of four points, in radians.

    p*: [K, 3] -> [K]. The angle of the p1->p2 bond, looking down it, between the planes
    (p0, p1, p2) and (p1, p2, p3).
    """
    b0 = p0 - p1
    b1 = p2 - p1
    b2 = p3 - p2
    b1 = b1 / (b1.norm(dim=-1, keepdim=True) + 1e-8)
    v = b0 - (b0 * b1).sum(-1, keepdim=True) * b1        # b0 with its b1 component removed
    w = b2 - (b2 * b1).sum(-1, keepdim=True) * b1
    x = (v * w).sum(-1)
    y = (torch.cross(b1, v, dim=-1) * w).sum(-1)
    return torch.atan2(y, x)


def planar_angle(p0: Tensor, p1: Tensor, p2: Tensor) -> Tensor:
    """Angle at p1 between p0 and p2, in radians. p*: [K, 3] -> [K]."""
    a = p0 - p1
    b = p2 - p1
    cos = (a * b).sum(-1) / (a.norm(dim=-1) * b.norm(dim=-1) + 1e-8)
    return torch.acos(cos.clamp(-1 + 1e-7, 1 - 1e-7))


def _sincos(angle: Tensor, valid: Tensor) -> Tensor:
    """[K] radians + [K] bool -> [K, 2]. Undefined angles become (0, 0).

    We store angles as (sin, cos) because -pi and +pi are the same rotation but look far
    apart as plain numbers. A real angle always has sin^2 + cos^2 = 1, so (0, 0) is a
    marker that cannot be confused with one.
    """
    out = torch.stack([angle.sin(), angle.cos()], dim=-1)
    return out * valid.unsqueeze(-1)


def node_features(coords: Tensor) -> Tensor:
    """Backbone geometry per residue. coords: [N, 4, 3] -> [N, 10].

    Columns: phi, psi, omega, virtual CA bond angle, virtual CA torsion, each as (sin, cos).
    The virtual angles describe the same twisting using only the CA trace, which is what
    the graph nodes sit on. Residues at the chain ends are missing a neighbour, so some of
    their angles are undefined and come out as (0, 0).
    """
    n, ca, c = coords[:, N_ATOM], coords[:, CA_ATOM], coords[:, C_ATOM]
    num = coords.shape[0]
    idx = torch.arange(num)
    prev, nxt, nxt2 = idx - 1, idx + 1, idx + 2
    has_prev, has_next = idx > 0, idx < num - 1
    has_next2 = idx < num - 2
    p, q, r = prev.clamp(min=0), nxt.clamp(max=num - 1), nxt2.clamp(max=num - 1)

    phi = dihedral(c[p], n, ca, c)                       # C(i-1), N(i), CA(i), C(i)
    psi = dihedral(n, ca, c, n[q])                       # N(i), CA(i), C(i), N(i+1)
    omega = dihedral(ca[p], c[p], n, ca)                 # CA(i-1), C(i-1), N(i), CA(i)
    bond = planar_angle(ca[p], ca, ca[q])                # CA(i-1), CA(i), CA(i+1)
    tors = dihedral(ca[p], ca, ca[q], ca[r])             # CA(i-1..i+2)

    return torch.cat([
        _sincos(phi, has_prev),
        _sincos(psi, has_next),
        _sincos(omega, has_prev),
        _sincos(bond, has_prev & has_next),
        _sincos(tors, has_prev & has_next & has_next2),
    ], dim=-1)                                           # [N, 10]


def rbf(dist: Tensor, n_bins: int = RBF_DIM,
        d_min: float = 2.0, d_max: float = 22.0) -> Tensor:
    """Radial basis expansion of a distance. [E] -> [E, n_bins].

    Gaussian bumps spread along the distance axis, so 6.2 A becomes a soft one-hot over
    distance ranges rather than a single scalar the network has to shape a response to.
    """
    centers = torch.linspace(d_min, d_max, n_bins, device=dist.device)
    sigma = (d_max - d_min) / n_bins
    return torch.exp(-(((dist.unsqueeze(-1) - centers) / sigma) ** 2))


def sep_onehot(sep: Tensor, bins: Sequence[int] = SEP_BINS) -> Tensor:
    """Sequence separation |i - j|, bucketed. [E] -> [E, len(bins) + 1].

    Neighbours in the chain are joined by a bond; neighbours only in space are a contact
    the fold created. Small separations are worth distinguishing exactly, large ones are
    not, so the buckets widen.
    """
    out = torch.zeros(sep.shape[0], len(bins) + 1, device=sep.device)
    bucket = torch.full_like(sep, len(bins))
    for i, upper in reversed(list(enumerate(bins))):
        bucket[sep <= upper] = i
    out[torch.arange(sep.shape[0]), bucket.long()] = 1.0
    return out


def edge_features(ca: Tensor, edge_index: Tensor) -> Tensor:
    """ca: [N, 3], edge_index: [2, E] -> [E, EDGE_FEAT_DIM]."""
    src, dst = edge_index
    dist = (ca[src] - ca[dst]).norm(dim=-1)              # [E]
    sep = (src - dst).abs()                              # [E]
    return torch.cat([rbf(dist), sep_onehot(sep)], dim=-1)
