#!/usr/bin/env python3
"""Generate a PolySIM chain and optionally prepare or run PEO–LiTFSI MD."""

from __future__ import annotations

import argparse
from fractions import Fraction
import json
import math
from pathlib import Path
import subprocess
import sys

import numpy as np
from rdkit import Chem
from scipy.spatial import cKDTree
from polysim.chemistry.conformers import build_mmff_conformer, save_conformer, save_conformer_sdf
from polysim.io.xyz import read_xyz
from polysim.xtb.calculator import run_xtb
from polysim.md.system import _rotation_matrix
from polysim.workflow import build_workflow

from run_equilibration import read_template, read_topology, reconstruct_images, rows, section

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/01-peo"
TERMS = ("Bonds", "Angles", "Dihedrals")
XIE_SALT_PAIRS = 50
XIE_MOLALITY = 1.5
XIE_PEO_REPEATS = 50


def composition(chain_mass, args):
    """Round the chain or salt count using the requested composition basis."""
    pairs = XIE_SALT_PAIRS
    if args.ratio is None:
        pairs_per_chain = XIE_MOLALITY * chain_mass / 1000
    else:
        pairs_per_chain = args.repeat_units / args.ratio
    chains = args.chains if args.chains is not None else max(1, round(pairs / pairs_per_chain))
    if args.chains is not None:
        pairs = round(chains * pairs_per_chain)
    if pairs < 1:
        raise ValueError("The requested loading rounds to zero salt pairs")
    return chains, pairs


def run_plan(args):
    nvt = 200_000 if args.nvt_steps is None else args.nvt_steps
    npt = 9_800_000 if args.npt_steps is None else args.npt_steps
    production = 5_000_000 if args.production_steps is None else args.production_steps
    equil_interval = args.equil_interval if args.equil_interval is not None else math.gcd(5000, nvt, npt)
    prod_interval = args.production_interval if args.production_interval is not None else math.gcd(1000, production)
    if min(nvt, npt, production, equil_interval, prod_interval) <= 0 or (
        nvt % equil_interval or npt % equil_interval or production % prod_interval
    ):
        raise ValueError("Stage step counts must be positive multiples of their output intervals")
    if not math.isfinite(args.temperature) or args.temperature <= 0:
        raise ValueError("Temperature must be positive")
    return {
        "nvt_steps": nvt, "npt_steps": npt, "production_steps": production,
        "equil_timestep": 0.5, "production_timestep": 1.0,
        "temperature": args.temperature, "seed": args.seed,
        "equil_interval": equil_interval, "production_interval": prod_interval,
    }



def peo_parameters(molecule, repeat_units, reference_atoms, reference_bonds):
    heavy = [a.GetIdx() for a in molecule.GetAtoms() if a.GetAtomicNum() != 1]
    neighbors = [[n.GetIdx() for n in a.GetNeighbors()] for a in molecule.GetAtoms()]
    ends = [i for i in heavy if sum(j in heavy for j in neighbors[i]) == 1]
    oxy = [i for i in ends if molecule.GetAtomWithIdx(i).GetSymbol() == "O"]
    if len(ends) != 2 or len(oxy) != 1:
        raise ValueError("MD supports linear H-capped PEO (e.g. [*]CCO[*])")
    path, previous, current = [], None, oxy[0]
    heavy_set = set(heavy)
    while current is not None and current not in path:
        path.append(current)
        following = [j for j in neighbors[current] if j != previous and j in heavy_set]
        if len(following) > 1:
            raise ValueError("Branched PEO chains are unsupported")
        previous, current = current, next(iter(following), None)
    symbols = "".join(molecule.GetAtomWithIdx(i).GetSymbol() for i in path)
    if symbols != "OCC" * repeat_units or len(path) != len(heavy):
        raise ValueError("The generated chain is outside the PEO force-field scope")
    source = next(i for i, row in reference_atoms.items() if int(row[2]) == 9)
    ref_path, previous = [], None
    while source is not None:
        ref_path.append(source)
        following = [j for j in reference_bonds[source] if j != previous
                     and int(reference_atoms[j][2]) not in (8, 10)]
        previous, source = source, next(iter(following), None)
    # Transfer the first three and last three sites verbatim. Use the interior
    # values of the reference chain for the intervening PEO repeat units.
    template = []
    for k in range(len(path)):
        if k < 3:
            template.append(ref_path[k])
        elif k >= len(path) - 3:
            template.append(ref_path[k - len(path)])
        else:
            template.append(ref_path[6 + k % 3])
    types = np.zeros(molecule.GetNumAtoms(), dtype=int)
    charges = np.zeros(len(types))
    for i, ref in zip(path, template):
        types[i], charges[i] = int(reference_atoms[ref][2]), float(reference_atoms[ref][3])
        hydrogens = [j for j in neighbors[i] if j not in heavy_set]
        ref_h = [j for j in reference_bonds[ref] if int(reference_atoms[j][2]) in (8, 10)]
        if len(hydrogens) != len(ref_h):
            raise ValueError("PEO hydrogen topology does not match the parameter template")
        for j, h in zip(hydrogens, ref_h):
            types[j], charges[j] = int(reference_atoms[h][2]), float(reference_atoms[h][3])
    # The reference's rounded charges leave a small net charge per repeat.
    correction = -float(charges.sum()) / len(charges)
    charges += correction
    return types, charges, neighbors, correction


def chain_terms(types, neighbors, reference_terms, atoms):
    result = {}
    paths = [(i,) for i in range(len(types))]
    for name in TERMS:
        paths = [path + (j,) for path in paths for j in neighbors[path[-1]] if j not in path]
        mapping = {}
        for coeff, *ids in reference_terms[name]:
            key = tuple(int(atoms[i][2]) for i in ids)
            if min(key) >= 7:
                key = min(key, key[::-1])
                if key in mapping and mapping[key] != coeff:
                    raise ValueError(f"Ambiguous PEO coefficient for {name} {key}")
                mapping[key] = coeff
        result[name] = []
        for path in paths:
            if path < path[::-1]:
                key = tuple(types[i] for i in path)
                key = min(key, key[::-1])
                if key not in mapping:
                    raise ValueError(f"No reference coefficient for {name} {key}")
                result[name].append((mapping[key], *path))
    return result


def reference_salt(atoms, bonds, bounds, reference_terms):
    lithium = next(i for i, row in atoms.items() if int(row[2]) == 1)
    nitrogen = next(i for i, row in atoms.items() if int(row[2]) == 2)
    anion, seen = [nitrogen], {nitrogen}
    for i in anion:
        for j in bonds[i]:
            if j not in seen:
                seen.add(j)
                anion.append(j)
    if len(anion) != 15:
        raise ValueError("Reference TFSI does not contain 15 bonded atoms")
    wrapped, images = reconstruct_images(
        {i: tuple(map(float, atoms[i][4:7])) for i in anion}, bonds, bounds)
    coordinates = np.array([wrapped[i] for i in anion]) + np.array(
        [images[i] for i in anion]) * np.array([hi-lo for lo, hi in bounds])
    index = {i: k for k, i in enumerate(anion)}
    terms = {name: [(coeff, *(index[i] for i in ids))
                    for coeff, *ids in reference_terms[name] if all(i in index for i in ids)]
             for name in TERMS}
    return (
        ("Li", np.zeros((1, 3)), [1], [float(atoms[lithium][3])],
         {name: [] for name in TERMS}),
        ("TFSI", coordinates, [int(atoms[i][2]) for i in anion],
         [float(atoms[i][3]) for i in anion], terms),
    )


def write_box(out, chain, salt, template, counts, args, correction, plan):
    lines = template
    mass_by_type = {int(i): float(m) for i, m in rows(lines, section(lines, "Masses"))}
    total_mass = sum(count * sum(mass_by_type[t] for t in molecule[2])
                     for molecule, count in zip((chain, *salt), counts))
    length = (total_mass * 1e24 / (6.02214076e23 * args.density)) ** (1 / 3)
    cutoff = read_template(EXAMPLE / "rbmd.json")["hyper_parameters"]["neighbor"]["cut_off"]
    if length <= 2 * cutoff:
        raise ValueError(f"Packed box length {length:.2f} Å must exceed twice the {cutoff:g} Å cutoff. Use more chains.")
    rng = np.random.default_rng(args.seed)
    positions, atom_rows, molecules = [], [], []
    terms = {name: [] for name in TERMS}
    for (species, coordinates, types, charges, entries), count in zip((chain, *salt), counts):
        centered = coordinates - coordinates.mean(axis=0)
        for _ in range(count):
            tree = cKDTree(np.vstack(positions), boxsize=length) if positions else None
            for _ in range(2000):
                rotated = centered @ _rotation_matrix(rng).T
                if np.any(np.ptp(rotated, axis=0) + args.minimum_distance >= length):
                    continue
                candidate = rotated + rng.uniform(0, length, size=3)
                wrapped = candidate % length
                if tree is None or np.all(tree.query(wrapped)[0] >= args.minimum_distance):
                    break
            else:
                raise ValueError(f"Could not pack {species}. Try a lower initial density.")
            offset = len(atom_rows)
            images = np.floor(candidate / length).astype(int)
            positions.append(wrapped)
            molecule_id = len(molecules) + 1
            molecules.append({"species": species, "first_id": offset + 1,
                              "last_id": offset + len(types)})
            for i, (kind, charge, xyz, image) in enumerate(zip(types, charges, wrapped, images), offset + 1):
                atom_rows.append(" ".join(map(str, (i, molecule_id, kind, charge, *xyz, *image))))
            for name in TERMS:
                terms[name].extend((coeff, *(offset + i + 1 for i in ids))
                                   for coeff, *ids in entries[name])
    if abs(math.fsum(float(row.split()[3]) for row in atom_rows)) > 1e-6:
        raise ValueError("Generated box is not charge neutral")
    coefficients = ("Masses", "Pair Coeffs", "Bond Coeffs", "Angle Coeffs", "Dihedral Coeffs")
    blocks = {name: rows(lines, section(lines, name)) for name in coefficients}
    header = ["PolySIM PEO-LiTFSI (REAL)", "", f"{len(atom_rows)} atoms"]
    header += [f"{len(terms[name])} {name.lower()}" for name in TERMS]
    header += ["", f"{len(mass_by_type)} atom types"]
    for name, label in zip(coefficients[2:], ("bond", "angle", "dihedral")):
        header.append(f"{sum(1 for _ in rows(lines, section(lines, name)))} {label} types")
    header += ["", *(f"0 {length:.17g} {axis}lo {axis}hi" for axis in "xyz")]
    for name in coefficients:
        header.extend(("", name, "", *(" ".join(row) for row in blocks[name])))
    header.extend(("", "Atoms # full", "", *atom_rows))
    for name, entries in terms.items():
        header.extend(("", name, "", *(" ".join(map(str, (i, *row)))
                                       for i, row in enumerate(entries, 1))))
    data = out / "packed.data"
    data.write_text("\n".join(header) + "\n")
    (out / "species_map.json").write_text(json.dumps({
        "molecules": molecules, "chains": counts[0], "salt_pairs": counts[1],
        "repeat_units_per_chain": args.repeat_units,
        "actual_eo_per_li": counts[0] * args.repeat_units / counts[1],
        "requested_eo_per_li": str(args.ratio) if args.ratio is not None else None,
        "target_molality_mol_kg": XIE_MOLALITY if args.ratio is None else None,
        "actual_molality_mol_kg": counts[1] * 1000 / (
            counts[0] * sum(mass_by_type[t] for t in chain[2])),
        "total_atoms": len(atom_rows), "packing_seed": args.seed,
        "polymer_charge_correction_e_per_atom": correction,
        "parameter_source": "examples/01-peo/peo+Li.data",
    }, indent=2) + "\n")
    config = read_template(EXAMPLE / "rbmd.json")
    config["init_configuration"]["read_data"].update(file=data.name, velocity_seed=args.seed)
    config["execution"].update(num_steps=plan["production_steps"],
                               timestep=plan["production_timestep"],
                               temperature=[plan["temperature"], plan["temperature"], 100])
    config["outputs"] = {
        "thermo_out": {"interval": plan["production_interval"]},
        "trajectory_out": {"interval": plan["production_interval"]},
    }
    (out / "rbmd.json").write_text(json.dumps(config, indent=2) + "\n")
    (out / "run_plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    return data


def peo_geometry(args, geometry):
    geometry.mkdir()
    chain = Chem.MolFromSmiles("OCC" * args.repeat_units)
    conformer = build_mmff_conformer(chain, random_seed=args.seed)
    sdf = save_conformer_sdf(conformer, geometry / "chain_mmff_explicit_h.sdf")
    initial = save_conformer(conformer, geometry / "chain_mmff.xyz")
    optimized = geometry / "chain_gfnff_opt.xyz"
    run_xtb(initial, optimized, method="gfnff", optimize=True, optimizer_engine="inertial",
            threads=args.xtb_threads, xtb_executable=args.xtb_executable)
    molecule = Chem.SDMolSupplier(str(sdf), removeHs=False)[0]
    species, coordinates, _ = read_xyz(optimized)
    if molecule is None or species != [a.GetSymbol() for a in molecule.GetAtoms()]:
        raise ValueError("PolySIM SDF topology and selected XYZ do not match")
    return molecule, coordinates


def prepare(args, out, geometry, plan):
    molecule, coordinates = peo_geometry(args, geometry)
    lines, span, atoms, bonds, _ = read_topology(EXAMPLE / "peo+Li.data")
    bounds = [next(tuple(map(float, line.split()[:2])) for line in lines[:span[0]]
                   if line.split()[-2:] == [axis+"lo", axis+"hi"]) for axis in "xyz"]
    reference_terms = {name: [tuple(map(int, row[1:])) for row in rows(lines, section(lines, name))]
                       for name in TERMS}
    types, charges, neighbors, correction = peo_parameters(molecule, args.repeat_units, atoms, bonds)
    chain = ("PEO", coordinates, types, charges,
             chain_terms(types, neighbors, reference_terms, atoms))
    salt = reference_salt(atoms, bonds, bounds, reference_terms)
    masses = {int(i): float(m) for i, m in rows(lines, section(lines, "Masses"))}
    chains, pairs = composition(sum(masses[t] for t in types), args)
    print(f"Packing {chains} chains and {pairs} LiTFSI pairs "
          f"(EO:Li={chains * args.repeat_units / pairs:g}:1)", flush=True)
    return write_box(out, chain, salt, lines, (chains, pairs, pairs), args, correction, plan)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    monomer = parser.add_mutually_exclusive_group(required=True)
    monomer.add_argument("--monomer", help="Two-ended pSMILES")
    monomer.add_argument("--monomer-file", type=Path)
    parser.add_argument("--repeat-units", "-n", type=int, default=XIE_PEO_REPEATS)
    parser.add_argument("--chains", type=int)
    parser.add_argument("--ratio", type=lambda value: Fraction(value.replace(":", "/")),
                        help="PEO repeat units per LiTFSI pair, e.g. 16:1")
    parser.add_argument("--run-rbmd", choices=("no", "prepare", "yes"), default="no")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rbmd", type=Path)
    parser.add_argument("--density", type=float, default=0.3, help="Starting density in g/cm3")
    parser.add_argument("--minimum-distance", type=float, default=2.0, help="Intermolecular separation in Å")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--xtb-threads", type=int, default=2)
    parser.add_argument("--xtb-executable", default="xtb")
    parser.add_argument("--temperature", type=float, default=353.0)
    parser.add_argument("--nvt-steps", type=int)
    parser.add_argument("--npt-steps", type=int)
    parser.add_argument("--production-steps", type=int)
    parser.add_argument("--equil-interval", type=int)
    parser.add_argument("--production-interval", type=int)
    parser.add_argument("--fit-ps", nargs=2, type=float, metavar=("START", "END"))
    args = parser.parse_args()
    md = args.run_rbmd != "no"
    if (args.repeat_units < 1 or (args.chains is not None and args.chains < 1) or
            args.seed < 1 or args.xtb_threads < 1 or
            any(not math.isfinite(v) or v <= 0 for v in (args.density, args.minimum_distance))):
        parser.error("Repeat count, chain count, seed, xTB threads, density and separation must be positive")
    if md and (args.repeat_units < 2 or (args.ratio is not None and args.ratio <= 0)):
        parser.error("MD requires at least two PEO repeat units and a positive ratio if supplied")
    if args.run_rbmd == "yes" and args.rbmd is None:
        parser.error("Running RBMD requires --rbmd")
    try:
        smiles = args.monomer if args.monomer is not None else args.monomer_file.read_text().strip()
        supplied = Chem.MolFromSmiles(smiles)
        expected = Chem.MolToSmiles(Chem.MolFromSmiles("[*]CCO[*]"))
        is_peo = supplied is not None and Chem.MolToSmiles(supplied) == expected
        if md and not is_peo:
            raise ValueError("The MD parameter library currently covers [*]CCO[*] only")
        out = args.out.resolve()
        out.mkdir(parents=True, exist_ok=False)
        (out / "monomer.psmiles.txt").write_text(smiles + "\n")
        geometry = out / "polysim"
        if not md and is_peo:
            peo_geometry(args, geometry)
            print(f"PEO chain geometry: {geometry}")
            return
        if not md:
            build_workflow(psmiles_file=out / "monomer.psmiles.txt", repeat_units=args.repeat_units,
                           chains=args.chains or 1, output_directory=geometry,
                           xtb_threads=args.xtb_threads, xtb_executable=args.xtb_executable,
                           density_g_cm3=args.density, random_seed=args.seed,
                           minimum_distance=args.minimum_distance)
            print(f"PolySIM outputs: {geometry}")
            return
        plan = run_plan(args)
        data = prepare(args, out, geometry, plan)
        print(f"RBMD inputs: {data}, {out / 'rbmd.json'}, {out / 'species_map.json'}", flush=True)
        if args.run_rbmd == "yes":
            subprocess.run([
                sys.executable, str(ROOT / "scripts/run_equilibration.py"),
                "--rbmd", str(args.rbmd), "--data", str(data), "--template", str(out / "rbmd.json"),
                "--out", str(out / "md"), "--plan", str(out / "run_plan.json"),
            ], check=True)
            from analyze_transport import analyze
            production = out / "md/03-production"
            analyze(production / "rbmd.trj", production / "final.data",
                    out / "species_map.json", production / "rbmd.json", out, args.fit_ps)
            from plot_transport import plot
            plot(out)
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"PolySIM workflow stopped: {exc}\n")


if __name__ == "__main__":
    main()
