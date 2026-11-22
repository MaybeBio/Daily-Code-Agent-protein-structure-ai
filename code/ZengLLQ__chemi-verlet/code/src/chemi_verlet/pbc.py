"""Periodic boundary condition geometry and O(N) cell-linked neighbor lists.

Supports orthorhombic and arbitrary triclinic simulation cells using fractional
coordinate transformations ``s = H^{-1} r`` and minimum-image displacement
vectors. Maintains a Verlet skin-buffered cell-linked neighbor list for
cutoff-bounded nonbonded interactions.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import numpy as np

from chemi_verlet.types import FloatArray, IntArray, SimulationBox


def wrap_positions(positions: FloatArray, box: SimulationBox) -> FloatArray:
    """Wrap atomic coordinates into the primary unit cell ``[0, 1)^3`` in fractional space.

    Parameters
    ----------
    positions:
        Atomic coordinates of shape ``(N, 3)`` in nm.
    box:
        Periodic simulation cell.

    Returns
    -------
    FloatArray
        Wrapped coordinates of shape ``(N, 3)`` in nm.
    """
    pos = np.asarray(positions, dtype=np.float64)
    if box.is_orthorhombic:
        diag = np.diag(box.vectors)
        return np.mod(pos, diag)
    frac = pos @ box.inv_vectors.T
    frac = frac - np.floor(frac)
    return frac @ box.vectors.T


def minimum_image_displacement(dr: FloatArray, box: SimulationBox) -> FloatArray:
    """Apply minimum-image convention to displacement vector(s) ``r_j - r_i``.

    Works for arbitrary shapes ``(..., 3)`` and both orthorhombic and triclinic boxes.
    """
    if box.is_orthorhombic:
        diag = np.diag(box.vectors)
        return dr - diag * np.round(dr / diag)
    frac = dr @ box.inv_vectors.T
    frac = frac - np.round(frac)
    return frac @ box.vectors.T


def minimum_image_pair_vectors(
    positions: FloatArray,
    box: SimulationBox,
) -> Tuple[FloatArray, FloatArray]:
    """Compute all-pairs minimum-image displacement matrix and distance matrix.

    Intended for small-to-medium systems (``N <= 600``) or analytical validation;
    larger systems should use :class:`CellListNeighborFinder`.
    """
    pos = np.asarray(positions, dtype=np.float64)
    dr = pos[None, :, :] - pos[:, None, :]
    dr_mic = minimum_image_displacement(dr, box)
    dist = np.linalg.norm(dr_mic, axis=-1)
    return dr_mic, dist


def compute_pair_list_direct(
    positions: FloatArray,
    box: SimulationBox,
    cutoff: float,
    exclusions: Optional[Dict[int, set[int]]] = None,
) -> Tuple[IntArray, IntArray]:
    """Exact O(N^2) reference pair list used to validate the O(N) cell-linked list."""
    n = positions.shape[0]
    if n < 2:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)
    _, dist = minimum_image_pair_vectors(positions, box)
    iu, ju = np.triu_indices(n, k=1)
    mask = dist[iu, ju] <= cutoff
    i_cand = iu[mask]
    j_cand = ju[mask]
    if exclusions:
        keep = [
            idx
            for idx, (a, b) in enumerate(zip(i_cand.tolist(), j_cand.tolist()))
            if b not in exclusions.get(a, set())
        ]
        return i_cand[keep].astype(np.int64), j_cand[keep].astype(np.int64)
    return i_cand.astype(np.int64), j_cand.astype(np.int64)


class CellListNeighborFinder:
    """O(N) 3D cell-linked Verlet neighbor list with skin-displacement rebuild guard.

    The simulation box is subdivided along its lattice vectors into at least 3 cells
    per dimension whenever box geometry allows. For small boxes where ``L < 3 * r_list``,
    it cleanly falls back to unique cell scanning so self-image aliasing never occurs.
    """

    def __init__(
        self,
        cutoff: float,
        skin: float = 0.15,
        exclusions: Optional[Dict[int, set[int]]] = None,
    ) -> None:
        if cutoff <= 0.0:
            raise ValueError("Neighbor cutoff must be strictly positive")
        if skin < 0.0:
            raise ValueError("Neighbor skin thickness must be non-negative")
        self.cutoff = float(cutoff)
        self.skin = float(skin)
        self.r_list = self.cutoff + self.skin
        self.exclusions = exclusions or {}
        self._ref_positions: Optional[FloatArray] = None
        self._ref_box_vectors: Optional[FloatArray] = None
        self._pair_i: IntArray = np.empty(0, dtype=np.int64)
        self._pair_j: IntArray = np.empty(0, dtype=np.int64)
        self.rebuild_count: int = 0

    def needs_rebuild(self, positions: FloatArray, box: SimulationBox) -> bool:
        """Return True if any atom moved more than ``skin / 2`` or box changed."""
        if self._ref_positions is None or self._ref_box_vectors is None:
            return True
        if positions.shape != self._ref_positions.shape:
            return True
        if not np.allclose(box.vectors, self._ref_box_vectors, rtol=1e-6, atol=1e-8):
            return True
        if self.skin == 0.0:
            return True
        disp = minimum_image_displacement(positions - self._ref_positions, box)
        max_disp = float(np.max(np.linalg.norm(disp, axis=1)))
        return 2.0 * max_disp >= self.skin

    def get_pairs(
        self,
        positions: FloatArray,
        box: SimulationBox,
        force_rebuild: bool = False,
    ) -> Tuple[IntArray, IntArray, FloatArray, FloatArray]:
        """Return active pairs ``(i, j)`` within ``cutoff`` along with ``dr`` and ``r``.

        Returns
        -------
        tuple
            ``(pair_i, pair_j, dr_ij, dist_ij)`` where ``dr_ij = min_image(r_j - r_i)``
            and ``dist_ij <= cutoff``.
        """
        if force_rebuild or self.needs_rebuild(positions, box):
            self._rebuild(positions, box)
        if self._pair_i.size == 0:
            empty_i = np.empty(0, dtype=np.int64)
            empty_f = np.empty((0, 3), dtype=np.float64)
            empty_d = np.empty(0, dtype=np.float64)
            return empty_i, empty_i, empty_f, empty_d
        dr = positions[self._pair_j] - positions[self._pair_i]
        dr = minimum_image_displacement(dr, box)
        dist = np.linalg.norm(dr, axis=1)
        within = dist <= self.cutoff
        return self._pair_i[within], self._pair_j[within], dr[within], dist[within]

    def _rebuild(self, positions: FloatArray, box: SimulationBox) -> None:
        """Partition atoms into 3D fractional cells and collect pairs within ``r_list``."""
        n = positions.shape[0]
        self._ref_positions = positions.copy()
        self._ref_box_vectors = box.vectors.copy()
        self.rebuild_count += 1

        if n < 2:
            self._pair_i = np.empty(0, dtype=np.int64)
            self._pair_j = np.empty(0, dtype=np.int64)
            return

        # Effective perpendicular widths of triclinic cell faces: w_k = V / |a_i x a_j|
        a0, a1, a2 = box.vectors[:, 0], box.vectors[:, 1], box.vectors[:, 2]
        w0 = box.volume / max(float(np.linalg.norm(np.cross(a1, a2))), 1e-12)
        w1 = box.volume / max(float(np.linalg.norm(np.cross(a2, a0))), 1e-12)
        w2 = box.volume / max(float(np.linalg.norm(np.cross(a0, a1))), 1e-12)
        widths = np.array([w0, w1, w2], dtype=np.float64)

        ncells = np.maximum(1, np.floor(widths / self.r_list).astype(np.int64))
        # Fall back to direct vectorized check when box is smaller than 3 cell widths
        if np.any(ncells < 3):
            self._pair_i, self._pair_j = compute_pair_list_direct(
                positions, box, self.r_list, self.exclusions
            )
            return

        frac = (positions @ box.inv_vectors.T) % 1.0
        cell_idx = np.floor(frac * ncells[None, :]).astype(np.int64) % ncells[None, :]

        cells: Dict[Tuple[int, int, int], List[int]] = {}
        for atom_idx in range(n):
            key = (int(cell_idx[atom_idx, 0]), int(cell_idx[atom_idx, 1]), int(cell_idx[atom_idx, 2]))
            cells.setdefault(key, []).append(atom_idx)

        nx, ny, nz = int(ncells[0]), int(ncells[1]), int(ncells[2])
        cand_i: List[int] = []
        cand_j: List[int] = []
        r_list_sq = self.r_list * self.r_list

        # Half-shell stencil of 14 neighbor cells (self + 13 forward offsets) prevents duplicates
        offsets = [
            (dx, dy, dz)
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for dz in (-1, 0, 1)
            if (dx > 0) or (dx == 0 and dy > 0) or (dx == 0 and dy == 0 and dz >= 0)
        ]

        for (cx, cy, cz), atoms_a in cells.items():
            arr_a = np.asarray(atoms_a, dtype=np.int64)
            for dx, dy, dz in offsets:
                nb_key = ((cx + dx) % nx, (cy + dy) % ny, (cz + dz) % nz)
                atoms_b = cells.get(nb_key)
                if not atoms_b:
                    continue
                if dx == 0 and dy == 0 and dz == 0:
                    m = len(atoms_a)
                    if m < 2:
                        continue
                    for p in range(m - 1):
                        ai = atoms_a[p]
                        excl = self.exclusions.get(ai, set())
                        sub_b = np.array([b for b in atoms_a[p + 1:] if b not in excl], dtype=np.int64)
                        if sub_b.size == 0:
                            continue
                        dr = minimum_image_displacement(positions[sub_b] - positions[ai], box)
                        d2 = np.sum(dr * dr, axis=1)
                        hits = sub_b[d2 <= r_list_sq]
                        for bj in hits.tolist():
                            a_min, b_max = (ai, bj) if ai < bj else (bj, ai)
                            cand_i.append(a_min)
                            cand_j.append(b_max)
                else:
                    arr_b = np.asarray(atoms_b, dtype=np.int64)
                    dr = minimum_image_displacement(
                        positions[None, arr_b, :] - positions[arr_a, None, :],
                        box,
                    )
                    d2 = np.sum(dr * dr, axis=2)
                    ii, jj = np.where(d2 <= r_list_sq)
                    for idx_a, idx_b in zip(arr_a[ii].tolist(), arr_b[jj].tolist()):
                        if idx_b in self.exclusions.get(idx_a, set()):
                            continue
                        a_min, b_max = (idx_a, idx_b) if idx_a < idx_b else (idx_b, idx_a)
                        cand_i.append(a_min)
                        cand_j.append(b_max)

        self._pair_i = np.asarray(cand_i, dtype=np.int64)
        self._pair_j = np.asarray(cand_j, dtype=np.int64)
