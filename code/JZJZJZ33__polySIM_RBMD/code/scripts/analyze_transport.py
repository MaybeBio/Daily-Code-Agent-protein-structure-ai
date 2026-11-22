#!/usr/bin/env python3
"""Analyze a fixed-volume REAL trajectory using polymer-frame collective displacements."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from run_equilibration import read_template, read_topology, rows, section, trajectory_frames

E_CHARGE = 1.602176634e-19
K_B = 1.380649e-23


def displacement_curve(series):
    """Mean squared displacement over all time origins, via FFT."""
    series = series - series[0]
    count = len(series)
    fft_size = 1 << (2 * count - 1).bit_length()
    spectrum = np.fft.rfft(series, n=fft_size, axis=0)
    correlation = np.fft.irfft((abs(spectrum) ** 2).sum(axis=1), n=fft_size)[:count]
    squares = np.r_[0.0, np.cumsum(np.einsum("ij,ij->i", series, series))]
    lags = np.arange(count)
    return np.maximum((squares[count] - squares[lags] + squares[count - lags]
                       - 2 * correlation) / (count - lags), 0.0)


def analyze(trajectory, data, species_file, config_file, out, fit_ps=None):
    lines, _, atoms, _, _ = read_topology(data)
    config = read_template(config_file)
    if (config["init_configuration"]["read_data"]["unit"].upper() != "REAL" or
            config["execution"]["ensemble"].upper() != "NVT"):
        raise ValueError("Transport analysis expects a REAL-unit NVT production run")
    masses = {int(i): float(m) for i, m in rows(lines, section(lines, "Masses"))}
    groups = {"PEO": [], "Li": [], "TFSI": []}
    occupied = set()
    metadata = json.loads(species_file.read_text())
    definitions = metadata.get("species", {
        "PEO": {"role": "polymer"},
        "Li": {"role": "cation", "charge_e": 1},
        "TFSI": {"role": "anion", "charge_e": -1},
    })
    role_keys = {"polymer": "PEO", "cation": "Li", "anion": "TFSI"}
    for name, definition in definitions.items():
        if definition.get("role") not in role_keys:
            raise ValueError(f"Unsupported species role for {name}")
        expected = {"cation": 1, "anion": -1}.get(definition["role"])
        if expected is not None and definition.get("charge_e") != expected:
            raise ValueError("This analyzer currently supports monovalent binary salts")
    molecules = metadata["molecules"]
    for molecule in molecules:
        ids = molecule.get("atom_ids")
        if ids is None:
            ids = list(range(molecule["first_id"], molecule["last_id"] + 1))
        if not ids or occupied.intersection(ids) or any(i not in atoms for i in ids):
            raise ValueError("Invalid species-map atom IDs")
        occupied.update(ids)
        name = molecule["species"]
        species = role_keys[definitions[name]["role"]]
        if species not in groups:
            raise ValueError("Species map disagrees with topology")
        groups[species].append(ids)
    if occupied != atoms.keys() or any(not entries for entries in groups.values()):
        raise ValueError("Species map must cover all atoms and all three species")
    if len(groups["Li"]) != len(groups["TFSI"]):
        raise ValueError("Monovalent salt counts must match")
    out.mkdir(parents=True, exist_ok=True)
    ids = sorted(atoms)
    mass = np.array([masses[int(atoms[i][2])] for i in ids])
    index_by_id = {atom_id: index for index, atom_id in enumerate(ids)}
    weights = np.zeros((len(ids), 3))
    polymer = [i for molecule in groups["PEO"] for i in molecule]
    weights[np.array([index_by_id[i] for i in polymer]), 0] = mass[np.array([index_by_id[i] for i in polymer])]
    weights[:, 0] /= weights[:, 0].sum()
    for column, species in enumerate(("Li", "TFSI"), 1):
        for molecule in groups[species]:
            index = np.array([index_by_id[i] for i in molecule])
            weights[index, column] = mass[index] / mass[index].sum()
        weights[:, column] -= len(groups[species]) * weights[:, 0]

    collective, steps = [], []
    ion_positions = {species: [] for species in ("Li", "TFSI")}
    box = None
    for step, bounds, coordinates, _ in trajectory_frames(trajectory, atoms, unwrapped=True, allow_incomplete_tail=True):
        if box is None:
            box = bounds
        elif not np.allclose(box, bounds, rtol=0, atol=1e-6):
            raise ValueError("Transport analysis requires a fixed box")
        xyz = np.array([coordinates[i] for i in ids])
        polymer_center = weights[:, 0] @ xyz
        for species in ion_positions:
            centers = []
            for molecule in groups[species]:
                indices = np.array([index_by_id[i] for i in molecule])
                centers.append(np.average(xyz[indices], axis=0, weights=mass[indices])
                               - polymer_center)
            ion_positions[species].append(centers)
        collective.append(weights[:, 1:].T @ xyz)
        steps.append(step)
    if len(steps) < 4 or steps[1] <= steps[0] or not np.all(np.diff(steps) == steps[1] - steps[0]):
        raise ValueError("Expected at least four uniformly spaced production frames")
    series = np.array(collective)
    dt_ps = (steps[1] - steps[0]) * config["execution"]["timestep"] / 1000
    temperature = config["execution"]["temperature"][1]
    volume = np.prod([hi - lo for lo, hi in box])
    lag = np.arange(len(steps) // 2 + 1) * dt_ps
    plus = displacement_curve(series[:, 0])[:len(lag)]
    minus = displacement_curve(series[:, 1])[:len(lag)]
    charge = displacement_curve(series[:, 0] - series[:, 1])[:len(lag)]
    cross = (plus + minus - charge) / 2
    self_msd = {}
    for species, positions in ion_positions.items():
        positions = np.asarray(positions)
        self_msd[species] = sum(
            (displacement_curve(positions[:, i])[:len(lag)]
             for i in range(positions.shape[1])), np.zeros(len(lag))
        ) / positions.shape[1]
    with (out / "transport_curves.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["lag_ps", "li_collective_A2", "tfsi_collective_A2",
                         "li_tfsi_cross_A2", "charge_collective_A2", "li_self_msd_A2", "tfsi_self_msd_A2"])
        writer.writerows(zip(lag, plus, minus, cross, charge, self_msd["Li"], self_msd["TFSI"]))
    result = {
        "status": "fit_window_required", "reference_frame": "polymer_mass_center",
        "charge_convention": "formal monovalent ion charges for transport",
        "species_definitions": definitions,
        "species_counts": {key: len(value) for key, value in groups.items()},
        "production_duration_ps": (steps[-1] - steps[0]) * config["execution"]["timestep"] / 1000,
        "temperature_K": temperature, "volume_A3": float(volume), "frames": len(steps),
    }
    if fit_ps is not None:
        if not (0 < fit_ps[0] < fit_ps[1] <= lag[-1] + 1e-12):
            raise ValueError(f"Fit window must lie inside the positive lag range up to {lag[-1]:g} ps")
        fit = (lag >= fit_ps[0]) & (lag <= fit_ps[1] + 1e-12)
        if fit.sum() < 5:
            raise ValueError("Fit window needs at least five trajectory lag points")
        diffusion = {
            species: float(np.polyfit(lag[fit], curve[fit], 1)[0] / 6 * 1e-8)
            for species, curve in self_msd.items()
        }
        result["self_diffusion_m2_s"] = diffusion
        result["sampling_note"] = "Single-trajectory estimates; convergence and replica uncertainty require further sampling."
        if all(value > 0 for value in diffusion.values()):
            result["nernst_einstein_conductivity_S_cm"] = float(
                E_CHARGE**2 * sum(len(groups[key]) * value for key, value in diffusion.items())
                / (K_B * temperature * volume * 1e-30) / 100)
            result["nernst_einstein_transference_number"] = diffusion["Li"] / sum(diffusion.values())
        slopes = np.polyfit(lag[fit], np.column_stack((plus, minus, cross, charge))[fit], 1)[0]
        result.update(status="no_positive_transport_slope", fit_ps=list(fit_ps))
        if slopes[3] > 0:
            fitted = np.polyval(np.polyfit(lag[fit], charge[fit], 1), lag[fit])
            residual = float(np.sum((charge[fit] - fitted)**2))
            variance = float(np.sum((charge[fit] - charge[fit].mean())**2))
            result.update(
                status="provisional_single_trajectory_fit",
                conductivity_S_cm=float(slopes[3] * 1e20 * E_CHARGE**2
                                        / (6 * K_B * temperature * volume)),
                lithium_transference_number=float((slopes[0] - slopes[2]) / slopes[3]),
                charge_fit_r2=1 - residual / variance if variance else None,
            )
    (out / "transport.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("trajectory", "data", "species", "config", "out"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--fit-ps", nargs=2, type=float, metavar=("START", "END"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        analyze(args.trajectory, args.data, args.species, args.config, args.out, args.fit_ps)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Transport analysis stopped: {exc}\n")


if __name__ == "__main__":
    main()
