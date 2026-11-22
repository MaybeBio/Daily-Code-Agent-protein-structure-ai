#!/usr/bin/env python3
"""Run a single-GPU RBMD full-topology system through NVT, NPT, and NVT."""

from __future__ import annotations

import argparse
from collections import deque
import copy
import csv
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

AXES = ("x", "y", "z")
SECTION = re.compile(r"^[A-Za-z][A-Za-z0-9 /_-]*$")
JSON_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', re.DOTALL)


def read_template(path):
    return json.loads(JSON_TOKEN.sub(
        lambda match: match[0] if match[0].startswith('"') else " ",
        path.read_text(encoding="utf-8-sig"),
    ))


def content(line):
    return line.split("#", 1)[0].strip()


def section(lines, name):
    start = next((i for i, line in enumerate(lines[1:], 1) if content(line) == name), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines))
                if SECTION.fullmatch(content(lines[i]))), len(lines))
    return start, end


def rows(lines, span):
    start, end = span
    for line in lines[start + 1:end]:
        if content(line):
            yield content(line).split()


def read_topology(path):
    lines = path.read_text().splitlines(keepends=True)
    atom_section = section(lines, "Atoms")
    if atom_section is None:
        raise ValueError("Input data has no Atoms section")
    if any(content(line).split()[-3:] == ["xy", "xz", "yz"] for line in lines[:atom_section[0]]):
        raise ValueError("Only orthogonal boxes are supported")
    atoms = {}
    for row in rows(lines, atom_section):
        if len(row) not in (7, 10) or int(row[0]) in atoms:
            raise ValueError("Expected unique atom_style full rows, with optional image flags")
        atoms[int(row[0])] = row
    if not atoms or set(atoms) != set(range(1, len(atoms) + 1)):
        raise ValueError("Expected contiguous atom IDs starting at 1")
    bonds = {atom: [] for atom in atoms}
    bond_section = section(lines, "Bonds")
    if bond_section is not None:
        for row in rows(lines, bond_section):
            a, b = map(int, row[2:4])
            bonds[a].append(b)
            bonds[b].append(a)
    masses = section(lines, "Masses")
    if masses is None:
        raise ValueError("Input data has no Masses section")
    mass_by_type = {int(row[0]): float(row[1]) for row in rows(lines, masses)}
    mass = sum(mass_by_type[int(row[2])] for row in atoms.values())
    if not math.isfinite(mass) or mass <= 0:
        raise ValueError("Input data has invalid total mass")
    return lines, atom_section, atoms, bonds, mass


def require_line(handle, expected):
    line = handle.readline()
    if not line.startswith(expected):
        raise ValueError(f"Expected trajectory record {expected!r}, got {line.strip()!r}")
    return line


def trajectory_frames(path, atoms, *, unwrapped=False, allow_incomplete_tail=False):
    axes = ("xu", "yu", "zu") if unwrapped else AXES
    required = ("id", "type", "q", *axes, "vx", "vy", "vz")
    with path.open() as handle:
        for header in handle:
            if header.strip() != "ITEM: TIMESTEP":
                raise ValueError("Malformed trajectory timestep header")
            step = int(handle.readline())
            require_line(handle, "ITEM: NUMBER OF ATOMS")
            if int(handle.readline()) != len(atoms):
                raise ValueError(f"Unexpected atom count at step {step}")
            if require_line(handle, "ITEM: BOX BOUNDS").split()[3:] != ["pp"] * 3:
                raise ValueError("Expected an orthogonal fully periodic trajectory")
            bounds = [tuple(map(float, handle.readline().split())) for _ in AXES]
            if any(len(pair) != 2 or not all(map(math.isfinite, pair)) or pair[1] <= pair[0]
                   for pair in bounds):
                raise ValueError(f"Invalid box at step {step}")
            columns = require_line(handle, "ITEM: ATOMS ").split()[2:]
            indices = [columns.index(name) for name in required]
            positions, velocities = {}, {}
            for _ in atoms:
                raw = handle.readline()
                row = raw.split()
                if allow_incomplete_tail and (not raw or not raw.endswith("\n")):
                    import warnings
                    warnings.warn(f"Ignoring incomplete final frame at step {step}")
                    return
                if len(row) != len(columns):
                    raise ValueError(f"Truncated or malformed atom row at step {step}")
                atom_id, kind, charge, *state = (row[index] for index in indices)
                atom_id = int(atom_id)
                atom = atoms.get(atom_id)
                if atom is None or atom_id in positions or int(kind) != int(atom[2]):
                    raise ValueError(f"Atom identity mismatch for ID {atom_id} at step {step}")
                if not math.isclose(float(charge), float(atom[3]), abs_tol=1e-6):
                    raise ValueError(f"Charge mismatch for ID {atom_id} at step {step}")
                state = tuple(map(float, state))
                if not all(map(math.isfinite, state)):
                    raise ValueError(f"Nonfinite state for ID {atom_id} at step {step}")
                positions[atom_id], velocities[atom_id] = state[:3], state[3:]
            yield step, bounds, positions, velocities


def reconstruct_images(positions, bonds, bounds):
    lengths = [hi - lo for lo, hi in bounds]
    wrapped = {atom: tuple(lo + (x - lo) % length
                           for x, (lo, _), length in zip(xyz, bounds, lengths))
               for atom, xyz in positions.items()}
    images = {}
    for root in wrapped:
        if root in images:
            continue
        images[root] = (0, 0, 0)
        queue = deque([root])
        while queue:
            a = queue.popleft()
            for b in bonds[a]:
                image = tuple(flag - round((y - x) / length)
                              for flag, x, y, length in zip(
                                  images[a], wrapped[a], wrapped[b], lengths))
                if b not in images:
                    images[b] = image
                    queue.append(b)
                elif images[b] != image:
                    raise ValueError(f"Inconsistent periodic bond images at bond {a}-{b}")
    return wrapped, images


def write_state(path, topology, frame):
    original, atom_section, atoms, bonds, _ = topology
    lines = original.copy()
    _, bounds, positions, velocities = frame
    wrapped, images = reconstruct_images(positions, bonds, bounds)
    found = set()
    for index, line in enumerate(lines[:atom_section[0]]):
        fields = content(line).split()
        for axis, (lo, hi) in zip(AXES, bounds):
            if fields[-2:] == [f"{axis}lo", f"{axis}hi"]:
                lines[index] = f"{lo:.17g} {hi:.17g} {axis}lo {axis}hi\n"
                found.add(axis)
    if found != set(AXES):
        raise ValueError("Input data is missing box bounds")
    start, end = atom_section
    lines[start + 1:end] = ["\n", *(
        " ".join((*row[:4], *(f"{x:.17g}" for x in wrapped[atom]),
                  *map(str, images[atom]))) + "\n"
        for atom, row in atoms.items()
    ), "\n"]
    velocity_rows = ["\n", *(
        f"{atom} " + " ".join(f"{v:.17g}" for v in velocities[atom]) + "\n"
        for atom in atoms
    ), "\n"]
    velocity_section = section(lines, "Velocities")
    if velocity_section is None:
        end = section(lines, "Atoms")[1]
        lines[end:end] = ["Velocities\n", *velocity_rows]
    else:
        start, end = velocity_section
        lines[start + 1:end] = velocity_rows
    path.write_text("".join(lines))


def collect_stage(stage, topology, steps, interval):
    atoms, mass = topology[2], topology[4]
    last = None
    with (stage / "density.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["step", "volume_A3", "density_g_cm3"])
        for frame in trajectory_frames(stage / "rbmd.trj", atoms):
            step, bounds, _, _ = frame
            expected = 0 if last is None else last[0] + interval
            if step != expected:
                raise ValueError(f"{stage.name}: expected trajectory step {expected}, got {step}")
            volume = math.prod(hi - lo for lo, hi in bounds)
            writer.writerow([step, volume, mass * 1e24 / (6.02214076e23 * volume)])
            last = frame
    if last is None or last[0] != steps:
        raise ValueError(f"{stage.name}: trajectory did not reach step {steps}")
    write_state(stage / "final.data", topology, last)


def stage_config(template, data, ensemble, steps, timestep, interval, args):
    config = copy.deepcopy(template)
    read_data = config["init_configuration"]["read_data"]
    read_data.update(file=str(data), velocity_seed=args.seed)
    execution = config["execution"]
    execution.update(ensemble=ensemble, integration_type="vv", num_steps=steps,
                     timestep=timestep, temp_ctrl_type="NOSE_HOOVER",
                     temperature=[args.temperature, args.temperature, args.temp_damp])
    if ensemble == "NPT":
        execution.update(press_ctrl_type="NOSE_HOOVER",
                         pressure=[args.pressure, args.pressure, args.press_damp])
    config["outputs"] = {
        "thermo_out": {"interval": interval},
        "trajectory_out": {"interval": interval},
        "analysis_postprocess": {"enabled": False},
    }
    return config


def main():
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rbmd", required=True, type=Path, help="Compiled single-GPU binary")
    parser.add_argument("--data", required=True, type=Path, help="Parameterized REAL/full LAMMPS data")
    parser.add_argument("--template", type=Path, default=repo / "examples/01-peo/rbmd.json")
    parser.add_argument("--out", required=True, type=Path, help="New run directory")
    parser.add_argument("--nvt-steps", type=int)
    parser.add_argument("--npt-steps", type=int)
    parser.add_argument("--production-steps", type=int)
    parser.add_argument("--equil-timestep", type=float, default=0.5, help="fs")
    parser.add_argument("--production-timestep", type=float, default=1.0, help="fs")
    parser.add_argument("--temperature", type=float, default=298.0, help="K")
    parser.add_argument("--pressure", type=float, default=1.0, help="atm")
    parser.add_argument("--temp-damp", type=float, default=100.0, help="fs")
    parser.add_argument("--press-damp", type=float, default=1000.0, help="fs")
    parser.add_argument("--equil-interval", type=int, default=100)
    parser.add_argument("--production-interval", type=int, default=100)
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--plan", type=Path, help="Use a PolySIM run_plan.json")
    args = parser.parse_args()
    if args.plan is not None:
        try:
            plan = read_template(args.plan)
            allowed = {"nvt_steps", "npt_steps", "production_steps", "equil_timestep",
                       "production_timestep", "temperature", "seed",
                       "equil_interval", "production_interval"}
            if not isinstance(plan, dict) or not set(plan) <= allowed:
                raise ValueError("Unexpected run plan keys")
            # Explicit CLI options override the portable plan.
            parser.set_defaults(**plan)
            args = parser.parse_args()
        except (OSError, ValueError) as exc:
            parser.error(f"Invalid run plan: {exc}")
    if any(value is None for value in (args.nvt_steps, args.npt_steps, args.production_steps)):
        parser.error("Provide all three stage step counts or a run plan")
    stages = (
        ("01-nvt", "NVT", args.nvt_steps, args.equil_timestep, args.equil_interval),
        ("02-npt", "NPT", args.npt_steps, args.equil_timestep, args.equil_interval),
        ("03-production", "NVT", args.production_steps, args.production_timestep,
         args.production_interval),
    )
    if any(steps <= 0 or interval <= 0 or steps % interval or
           not math.isfinite(dt) or dt <= 0 for _, _, steps, dt, interval in stages):
        parser.error("Each stage needs positive steps, timestep, and an interval dividing its steps")
    if (args.seed <= 0 or not math.isfinite(args.pressure) or
            any(not math.isfinite(value) or value <= 0
                for value in (args.temperature, args.temp_damp, args.press_damp))):
        parser.error("Invalid temperature, pressure, damping, or seed")
    try:
        template = read_template(args.template)
        read_data = template["init_configuration"]["read_data"]
        if (read_data["unit"].upper(), read_data["atom_style"].lower()) != ("REAL", "full"):
            raise ValueError("Expected a REAL/full template")
        if template["hyper_parameters"]["force_field"]["type"].upper() != "CVFF":
            raise ValueError("Expected a CVFF template with parameters matching the input data")
        if any(key in read_data for key in ("replicate", "replicate_dims")):
            raise ValueError("Provide a complete box and a template without replication")
        topology = read_topology(args.data)
        binary = args.rbmd.resolve(strict=True)
        out = args.out.resolve()
        out.mkdir(parents=True, exist_ok=False)
        data = out / "packed.data"
        shutil.copyfile(args.data, data)
        for name, ensemble, steps, dt, interval in stages:
            stage = out / name
            stage.mkdir()
            config = stage / "rbmd.json"
            config.write_text(json.dumps(
                stage_config(template, data, ensemble, steps, dt, interval, args), indent=2
            ) + "\n")
            log = stage / "run.log"
            print(f"{name}: {steps} steps, log: {log}", flush=True)
            with log.open("w") as handle:
                result = subprocess.run([str(binary), "-j", config.name], cwd=stage,
                                        stdout=handle, stderr=subprocess.STDOUT)
            if result.returncode:
                raise ValueError(f"{name}: RBMD exited with status {result.returncode}. See {log}")
            collect_stage(stage, topology, steps, interval)
            data = stage / "final.data"
        print(f"Completed all stages. Production trajectory: {stage / 'rbmd.trj'}")
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"RBMD workflow stopped: {exc}\n")


if __name__ == "__main__":
    main()
