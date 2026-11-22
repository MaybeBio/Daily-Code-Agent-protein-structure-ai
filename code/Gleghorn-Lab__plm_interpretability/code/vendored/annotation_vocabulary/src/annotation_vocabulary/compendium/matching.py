"""Constructed negatives matched to the positives on lineage and length: the single-protein form of Atlas v3's program.

A view that builds negatives (an EC view's non-enzymes, a binary property's absent class) gives the positives and the candidate
negatives, each with a lineage stratum (its taxon at one rank), a length bin and a cluster. `match_negatives` chooses `ratio`
negatives per positive so that their count in every (stratum, bin) cell, and in each margin, sits as close to the positives'
as the candidates allow. The counts come from an integer program over the cells, each gap scaled by its target as Atlas v3 scales
its terms (`atlas.v3.negatives.ilp_negatives`), solved by HiGHS through scipy; within a cell candidates are taken in a seeded
order, at most `cluster_cap` from one cluster, so no family supplies a stratum's negatives. Logan, 2026-10-20: the gates are
lineage and length; study depth, composition and the other attributes of the shortcut registry are reported (`audit.py`).

`match_cells` matches two classes that are both drawn, as EC v2 drew enzymes and non-enzymes: each (stratum, bin) cell keeps as
many of the first as its second can match at `ratio` each, and those, so the share is the same in every cell and a cell one class
lacks keeps neither. The program keeps its positives whole and cannot balance a stratum the candidates lack; on the compendium's
EC view the classes sit in different lineages, and only the cell match passed the gate (the build experiment, 2026-10-21).

This moves to `foundry.datasets` when a second project consumes it.
"""

from __future__ import annotations

import bisect
import hashlib
import math

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass


LENGTH_EDGES = (100, 200, 300, 400, 600, 800, 1200)
Cell = tuple[str, int]


@dataclass(frozen=True, slots=True)
class Candidate:
    protein_id: str
    stratum: str
    length_bin: int
    cluster: str


def length_bin(length: int, edges: Sequence[int] = LENGTH_EDGES) -> int:
    """The bin of a length among ascending `edges`: by default 0 under 100 residues, then 100 to 199, 200 to 299, 300 to 399, 400
    to 599, 600 to 799, 800 to 1,199, and 1,200 or more."""
    return bisect.bisect_right(edges, length)


def _rank(seed: int, protein: str) -> str:
    return hashlib.sha256(f"{seed}:{protein}".encode()).hexdigest()


def available(candidates: Sequence[Candidate], cluster_cap: int) -> Counter[Cell]:
    """How many candidates each cell can give with at most `cluster_cap` from one cluster."""
    per_cluster: Counter[tuple[str, int, str]] = Counter((item.stratum, item.length_bin, item.cluster) for item in candidates)
    found: Counter[Cell] = Counter()
    for (stratum, bin_index, _cluster), count in per_cluster.items():
        found[(stratum, bin_index)] += min(count, cluster_cap)
    return found


def objective(counts: Mapping[Cell, int], targets: Mapping[Cell, float]) -> float:
    """The program's cost of `counts`: every cell's gap and every margin's gap, each divided by its target (at least 1)."""
    cells = set(counts) | set(targets)
    cost = sum(abs(counts.get(cell, 0) - targets.get(cell, 0.0)) / max(targets.get(cell, 0.0), 1.0) for cell in cells)
    for axis in (0, 1):
        chosen: Counter[object] = Counter()
        wanted: dict[object, float] = {}
        for cell in cells:
            chosen[cell[axis]] += counts.get(cell, 0)
            wanted[cell[axis]] = wanted.get(cell[axis], 0.0) + targets.get(cell, 0.0)
        cost += sum(abs(chosen[key] - wanted[key]) / max(wanted[key], 1.0) for key in wanted)
    return cost


def solve_counts(targets: Mapping[Cell, float], capacity: Mapping[Cell, int], total: int, *, time_limit: float = 600.0) -> dict[Cell, int]:
    """Integer counts per cell, summing to `total` and within `capacity`, that minimize `objective`.

    The constraint matrix is sparse: a view matched on a fine lineage rank has thousands of cells, and each row names one gap and
    the cells it sums."""
    import numpy as np

    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_matrix

    cells = sorted(cell for cell, room in capacity.items() if room > 0)
    if total > sum(capacity[cell] for cell in cells):
        raise ValueError(f"{total} negatives asked of {sum(capacity.values())} available")
    strata = sorted({cell[0] for cell in (*cells, *targets)})
    bins = sorted({cell[1] for cell in (*cells, *targets)})
    n, s, b = len(cells), len(strata), len(bins)
    # Columns: y (n cell counts), cell gaps (n), stratum gaps (s), bin gaps (b).
    columns = 2 * n + s + b
    cost = np.zeros(columns)
    cell_target = np.array([targets.get(cell, 0.0) for cell in cells])  # (n,)
    stratum_target, bin_target = np.zeros(s), np.zeros(b)  # (s,), (b,)
    stratum_of, bin_of = {name: place for place, name in enumerate(strata)}, {name: place for place, name in enumerate(bins)}
    for cell, value in targets.items():
        stratum_target[stratum_of[cell[0]]] += value
        bin_target[bin_of[cell[1]]] += value
    cost[n:2 * n] = 1.0 / np.maximum(cell_target, 1.0)
    cost[2 * n:2 * n + s] = 1.0 / np.maximum(stratum_target, 1.0)
    cost[2 * n + s:] = 1.0 / np.maximum(bin_target, 1.0)
    entries: list[tuple[int, int, float]] = []  # (row, column, coefficient)
    lower: list[float] = []
    upper: list[float] = []

    def constrain(coefficients: Iterable[tuple[int, float]], low: float, high: float) -> None:
        row = len(lower)
        entries.extend((row, column, value) for column, value in coefficients)
        lower.append(low)
        upper.append(high)

    constrain(((index, 1.0) for index in range(n)), total, total)
    for index in range(n):
        # gap >= |y - t|
        constrain(((n + index, 1.0), (index, -1.0)), -cell_target[index], np.inf)
        constrain(((n + index, 1.0), (index, 1.0)), cell_target[index], np.inf)
    members: dict[tuple[int, int], list[int]] = {}
    for index, cell in enumerate(cells):
        members.setdefault((0, stratum_of[cell[0]]), []).append(index)
        members.setdefault((1, bin_of[cell[1]]), []).append(index)
    for offset, target, axis in ((2 * n, stratum_target, 0), (2 * n + s, bin_target, 1)):
        for position in range(len(target)):
            inside = members.get((axis, position), [])
            constrain(((offset + position, 1.0), *((index, -1.0) for index in inside)), -target[position], np.inf)
            constrain(((offset + position, 1.0), *((index, 1.0) for index in inside)), target[position], np.inf)
    row_index, column_index, value = (np.array(part) for part in zip(*entries, strict=True))  # (z,) each
    matrix = coo_matrix((value, (row_index, column_index)), shape=(len(lower), columns)).tocsr()  # (rows, columns)
    integrality = np.zeros(columns)
    integrality[:n] = 1
    bounds = Bounds(np.zeros(columns), np.concatenate([[capacity[cell] for cell in cells], np.full(columns - n, np.inf)]))
    solution = milp(cost, constraints=LinearConstraint(matrix, lower, upper), integrality=integrality, bounds=bounds,
                    options={"time_limit": time_limit})
    if solution.x is None:
        raise RuntimeError(f"the matching program found no solution: {solution.message}")
    return {cell: int(round(solution.x[index])) for index, cell in enumerate(cells) if round(solution.x[index]) > 0}


def match_negatives(
    positives: Sequence[Candidate], candidates: Sequence[Candidate], *, ratio: float = 1.0, cluster_cap: int = 1, seed: int = 42,
) -> tuple[list[str], dict[str, object]]:
    """Negatives for `positives` chosen from `candidates`, and a report of the gaps the choice leaves.

    The candidates never include a positive; asking for more negatives than the capped candidates hold raises.
    """
    overlap = {item.protein_id for item in positives} & {item.protein_id for item in candidates}
    if overlap:
        raise ValueError(f"{len(overlap)} candidates are positives, such as {sorted(overlap)[0]}")
    targets: dict[Cell, float] = {}
    for item in positives:
        targets[(item.stratum, item.length_bin)] = targets.get((item.stratum, item.length_bin), 0.0) + ratio
    total = math.floor(ratio * len(positives) + 0.5)
    counts = solve_counts(targets, available(candidates, cluster_cap), total)
    chosen: list[str] = []
    taken: Counter[tuple[Cell, str]] = Counter()
    by_cell: dict[Cell, list[Candidate]] = {}
    for item in candidates:
        by_cell.setdefault((item.stratum, item.length_bin), []).append(item)
    for cell, wanted in sorted(counts.items()):
        for item in sorted(by_cell[cell], key=lambda candidate: _rank(seed, candidate.protein_id)):
            if wanted == 0:
                break
            if taken[(cell, item.cluster)] < cluster_cap:
                taken[(cell, item.cluster)] += 1
                chosen.append(item.protein_id)
                wanted -= 1
    report = {
        "positives": len(positives), "negatives": len(chosen), "ratio": ratio, "cluster_cap": cluster_cap,
        "objective": objective(counts, targets), "cells": len(targets),
        "cells_short": sum(1 for cell, value in targets.items() if counts.get(cell, 0) < value),
    }
    return sorted(chosen), report


def capped(items: Sequence[Candidate], cluster_cap: int, seed: int) -> list[Candidate]:
    """`items` in seeded order, keeping at most `cluster_cap` from one cluster."""
    taken: Counter[str] = Counter()
    found = []
    for item in sorted(items, key=lambda candidate: _rank(seed, candidate.protein_id)):
        if taken[item.cluster] < cluster_cap:
            taken[item.cluster] += 1
            found.append(item)
    return found


def match_cells(
    first: Sequence[Candidate], second: Sequence[Candidate], *, ratio: float, cluster_cap: int = 1, seed: int = 42,
) -> tuple[list[str], list[str], dict[str, object]]:
    """`first` and `second` matched within each (stratum, length bin) cell, and a report.

    A cell keeps as many of `first` as its `second` can match at `ratio` each, and `ratio` of `second` for each (rounded half up),
    at most `cluster_cap` of either from one cluster, each class taken in a seeded order; a cell one class lacks keeps neither.
    """
    overlap = {item.protein_id for item in first} & {item.protein_id for item in second}
    if overlap:
        raise ValueError(f"{len(overlap)} proteins are in both classes, such as {sorted(overlap)[0]}")
    cells: dict[Cell, tuple[list[Candidate], list[Candidate]]] = {}
    for side, items in enumerate((first, second)):
        for item in items:
            cells.setdefault((item.stratum, item.length_bin), ([], []))[side].append(item)
    kept_first: list[str] = []
    kept_second: list[str] = []
    matched = 0
    for cell in sorted(cells):
        ones, others = (capped(items, cluster_cap, seed) for items in cells[cell])
        count = min(len(ones), math.floor(len(others) / ratio))
        drawn = min(len(others), math.floor(ratio * count + 0.5))
        matched += count > 0
        kept_first.extend(item.protein_id for item in ones[:count])
        kept_second.extend(item.protein_id for item in others[:drawn])
    report = {"first": len(first), "second": len(second), "kept_first": len(kept_first), "kept_second": len(kept_second),
              "ratio": ratio, "cluster_cap": cluster_cap, "cells": len(cells), "matched_cells": matched}
    return sorted(kept_first), sorted(kept_second), report
