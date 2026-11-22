"""Strict 7-bit ASCII terminal visualizer for MD, FEP/MBAR, WHAM, docking, and MSMs.

Every character produced by this module lies strictly in ASCII range 0..127 so
output never triggers UnicodeEncodeError on Windows cp1252 or headless CI pipes.
"""

from __future__ import annotations

from typing import List, Sequence
import numpy as np

from chemi_verlet.types import (
    DockingScoreBreakdown,
    FloatArray,
    FreeEnergyEstimate,
    MarkovModelResult,
    PMFProfile,
    Trajectory,
)


def assert_strict_ascii(text: str) -> str:
    """Verify every code point in ``text`` is 7-bit ASCII (0..127) and return it."""
    for idx, ch in enumerate(text):
        if ord(ch) > 127:
            raise ValueError(f"Non-ASCII character {ch!r} (U+{ord(ch):04X}) at index {idx}")
    return text


def _ascii_line_plot(
    x: FloatArray,
    y: FloatArray,
    title: str,
    x_label: str,
    y_label: str,
    width: int = 58,
    height: int = 12,
    y_err: OptionalArray = None,
) -> str:
    """Render an ASCII scatter/line plot with axes, labels, and optional error bars."""
    valid = ~np.isnan(y)
    xv = np.asarray(x[valid], dtype=np.float64)
    yv = np.asarray(y[valid], dtype=np.float64)
    if xv.size == 0:
        return f"+-- {title} (no valid data) --+"

    y_lo_arr = yv if y_err is None else (yv - np.asarray(y_err[valid], dtype=np.float64))
    y_hi_arr = yv if y_err is None else (yv + np.asarray(y_err[valid], dtype=np.float64))
    y_min = float(np.min(y_lo_arr))
    y_max = float(np.max(y_hi_arr))
    if abs(y_max - y_min) < 1e-9:
        y_min -= 1.0
        y_max += 1.0

    x_min, x_max = float(np.min(xv)), float(np.max(xv))
    if abs(x_max - x_min) < 1e-9:
        x_max = x_min + 1.0

    canvas = [[" " for _ in range(width)] for _ in range(height)]
    for idx in range(xv.size):
        col = int(round((xv[idx] - x_min) / (x_max - x_min) * (width - 1)))
        col = max(0, min(width - 1, col))
        row = int(round((y_max - yv[idx]) / (y_max - y_min) * (height - 1)))
        row = max(0, min(height - 1, row))
        if y_err is not None:
            r_lo = int(round((y_max - y_hi_arr[idx]) / (y_max - y_min) * (height - 1)))
            r_hi = int(round((y_max - y_lo_arr[idx]) / (y_max - y_min) * (height - 1)))
            r_lo = max(0, min(height - 1, r_lo))
            r_hi = max(0, min(height - 1, r_hi))
            for rr in range(r_lo, r_hi + 1):
                if canvas[rr][col] == " ":
                    canvas[rr][col] = ":"
        canvas[row][col] = "*"

    lines = [f"=== {title} ({y_label} vs {x_label}) ==="]
    for r in range(height):
        val = y_max - (r / max(1, height - 1)) * (y_max - y_min)
        lines.append(f"{val:9.2f} |{''.join(canvas[r])}|")
    lines.append(f"{'':9s} +{'-' * width}+")
    lines.append(f"{'':9s} {x_min:<10.3f}{' ' * max(1, width - 20)}{x_max:>10.3f}")
    return assert_strict_ascii("\n".join(lines))


OptionalArray = FloatArray | None


def render_energy_profile(trajectory: Trajectory) -> str:
    """Render ASCII trajectory potential and kinetic temperature diagnostics."""
    t = trajectory.times()
    u = trajectory.potential_energies()
    temp = trajectory.temperatures()
    p1 = _ascii_line_plot(t, u, "Potential Energy Trajectory", "time (ps)", "U (kJ/mol)")
    p2 = _ascii_line_plot(t, temp, "Kinetic Temperature", "time (ps)", "T (K)", height=8)
    return assert_strict_ascii(p1 + "\n\n" + p2)


def render_rdf_plot(r_nm: FloatArray, g_r: FloatArray) -> str:
    """Render ASCII Radial Distribution Function g(r) curve."""
    return _ascii_line_plot(r_nm, g_r, "Radial Distribution Function g(r)", "r (nm)", "g(r)", height=10)


def render_mbar_summary(est: FreeEnergyEstimate) -> str:
    """Render ASCII MBAR/BAR/TI/FEP comparison table and state overlap matrix."""
    ramp = " .:-=+*#@"
    k = est.overlap_matrix.shape[0]
    lines: List[str] = [
        "=== Alchemical Free Energy Summary (kJ/mol) ===",
        f"  MBAR   : {est.delta_g_mbar:10.3f} +/- {est.sigma_mbar:6.3f}",
        f"  BAR    : {est.delta_g_bar:10.3f} +/- {est.sigma_bar:6.3f}",
        f"  TI     : {est.delta_g_ti:10.3f} +/- {est.sigma_ti:6.3f}",
        f"  FEP fwd: {est.delta_g_fep_fwd:10.3f} | rev: {est.delta_g_fep_rev:10.3f} "
        f"| hyst: {est.hysteresis_kj_mol:6.3f}",
        "",
        "--- MBAR State Overlap Matrix (ramp ' .:-=+*#@') ---",
    ]
    header = "    " + " ".join(f"W{j:<2d}" for j in range(k))
    lines.append(header)
    for i in range(k):
        cells = []
        for j in range(k):
            val = float(np.clip(est.overlap_matrix[i, j], 0.0, 1.0))
            sym = ramp[min(len(ramp) - 1, int(round(val * (len(ramp) - 1))))]
            cells.append(f"{sym}{sym} ")
        ess = float(est.effective_sample_sizes[i])
        lines.append(f"W{i:<2d} " + "".join(cells) + f" (ESS={ess:5.1f})")

    lam_idx = np.arange(k, dtype=np.float64)
    curve = _ascii_line_plot(
        lam_idx,
        est.window_free_energies,
        "Cumulative Alchemical Free Energy",
        "window index",
        "dG (kJ/mol)",
        y_err=est.window_uncertainties,
        height=9,
    )
    lines.append("")
    lines.append(curve)
    return assert_strict_ascii("\n".join(lines))


def render_pmf_profile(pmf: PMFProfile) -> str:
    """Render ASCII WHAM Potential of Mean Force curve with bootstrap error bars."""
    plot = _ascii_line_plot(
        pmf.bin_centers,
        pmf.pmf_kj_mol,
        f"WHAM PMF (iters={pmf.iterations}, res={pmf.residual:.2e})",
        "xi (nm)",
        "W(xi) (kJ/mol)",
        y_err=pmf.pmf_uncertainty_kj_mol,
        height=11,
    )
    ov_str = ", ".join(f"{v:.2f}" for v in pmf.overlap_fractions.tolist())
    return assert_strict_ascii(f"{plot}\nWindow Bhattacharyya overlaps: [{ov_str}]")


def render_docking_summary(score: DockingScoreBreakdown, smiles: str) -> str:
    """Render ASCII protein-ligand Vina + GBSA docking score decomposition."""
    lines = [
        f"=== Structure-Based Docking Score ({smiles}) ===",
        f"  Total Binding Score : {score.total_score:9.3f} kJ/mol",
        f"  Gauss1 Attraction   : {score.gauss1:9.3f} kJ/mol",
        f"  Gauss2 Broad        : {score.gauss2:9.3f} kJ/mol",
        f"  Steric Repulsion    : {score.repulsion:9.3f} kJ/mol",
        f"  Hydrophobic Contact : {score.hydrophobic:9.3f} kJ/mol",
        f"  Hydrogen Bonding    : {score.hbond:9.3f} kJ/mol",
        f"  GBSA Desolvation    : {score.gbsa_desolvation:9.3f} kJ/mol",
        f"  Torsion Entropy Pen : {score.torsion_entropy:9.3f} kJ/mol",
        f"  Pose Shift RMSD     : {score.rmsd_from_initial:9.4f} nm",
    ]
    return assert_strict_ascii("\n".join(lines))


def render_msm_summary(msm: MarkovModelResult) -> str:
    """Render ASCII Markov State Model stationary populations and implied timescales."""
    lines = [
        f"=== Reversible Markov State Model (states={msm.n_states}, lag={msm.lag_time_ps:.3f} ps) ===",
        f"  Chapman-Kolmogorov Error ||T(tau)^2 - T(2tau)||_F : {msm.ck_error:.4f}",
        "  Stationary Distribution pi:",
    ]
    for s_idx, p_val in enumerate(msm.stationary_distribution.tolist()):
        bar_len = int(round(p_val * 32))
        lines.append(f"    State {s_idx}: [{'#' * bar_len}{'.' * (32 - bar_len)}] {p_val:6.3f}")
    lines.append("  Implied Timescales (ps):")
    for idx, its in enumerate(msm.implied_timescales_ps.tolist()):
        lines.append(f"    Mode {idx + 1}: {its:10.4f} ps (lambda={msm.eigenvalues[idx + 1]:.4f})")
    return assert_strict_ascii("\n".join(lines))


def render_horizontal_bars(labels: Sequence[str], values: Sequence[float], title: str, width: int = 30) -> str:
    """Render a compact 7-bit ASCII horizontal bar chart."""
    max_v = max([abs(v) for v in values] + [1e-9])
    lines = [f"=== {title} ==="]
    for lbl, val in zip(labels, values):
        n_bars = int(round(abs(val) / max_v * width))
        lines.append(f"  {lbl:<16s} | {'#' * n_bars:<{width}s} | {val:8.3f}")
    return assert_strict_ascii("\n".join(lines))
