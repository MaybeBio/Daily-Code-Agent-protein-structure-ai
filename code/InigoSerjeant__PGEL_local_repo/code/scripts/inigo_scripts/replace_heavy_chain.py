#!/usr/bin/env python
"""Replace chain H in 5UDC_HLF_clean with a generated heavy-chain variant."""

import argparse
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPLEX = ROOT / "examples/input_pdbs/5UDC_HLF_clean.pdb"
DEFAULT_VARIANT_DIR = ROOT / "examples/5UDC_H_only_outputs/H29-34_94-114_variants"
DEFAULT_OUTPUT_DIR = ROOT / "examples/5UDC_H_chain_replacements"


def parse_ranges(value):
    ranges = []
    for item in value.split(","):
        start, end = item.split("-", maxsplit=1)
        ranges.append((int(start), int(end)))
    return ranges


def residue_key(line):
    return int(line[22:26]), line[26]


def read_chain(path, chain_id):
    records = []
    residues = {}
    with path.open() as pdb_file:
        for line in pdb_file:
            if line.startswith("ATOM  ") and line[21] == chain_id:
                key = residue_key(line)
                residues.setdefault(key, {"name": line[17:20], "ca": None})
                if line[12:16].strip() == "CA" and line[16] in (" ", "A"):
                    residues[key]["ca"] = np.array(
                        [float(line[start : start + 8]) for start in (30, 38, 46)]
                    )
                records.append(line.rstrip("\n"))
    if not residues:
        raise ValueError(f"No ATOM records for chain {chain_id!r} in {path}")
    missing_ca = [key for key, residue in residues.items() if residue["ca"] is None]
    if missing_ca:
        raise ValueError(f"Chain {chain_id!r} in {path} lacks CA atoms at {missing_ca[:5]}")
    return records, residues


def fit_variant(variant_records, target_residues, variant_residues, excluded_ranges):
    if target_residues.keys() != variant_residues.keys():
        missing = sorted(target_residues.keys() - variant_residues.keys())
        extra = sorted(variant_residues.keys() - target_residues.keys())
        raise ValueError(
            "Target and variant chain residue numbering differs; "
            f"missing in variant: {missing[:5]}, extra in variant: {extra[:5]}"
        )

    anchor_keys = [
        key
        for key in target_residues
        if target_residues[key]["name"] == variant_residues[key]["name"]
        and not any(start <= key[0] <= end for start, end in excluded_ranges)
    ]
    if len(anchor_keys) < 3:
        raise ValueError(f"Only {len(anchor_keys)} conserved alignment residues found")

    moving = np.stack([variant_residues[key]["ca"] for key in anchor_keys])
    fixed = np.stack([target_residues[key]["ca"] for key in anchor_keys])
    moving_center = moving.mean(axis=0)
    fixed_center = fixed.mean(axis=0)
    u, _, vt = np.linalg.svd((moving - moving_center).T @ (fixed - fixed_center))
    correction = np.eye(3)
    correction[-1, -1] = np.linalg.det(u @ vt)
    rotation = u @ correction @ vt

    transformed_records = []
    for line in variant_records:
        coordinates = np.array(
            [float(line[start : start + 8]) for start in (30, 38, 46)]
        )
        aligned = (coordinates - moving_center) @ rotation + fixed_center
        transformed_records.append(
            line[:21]
            + "H"
            + line[22:30]
            + "".join(f"{coordinate:8.3f}" for coordinate in aligned)
            + line[54:]
        )

    fitted = (moving - moving_center) @ rotation + fixed_center
    rmsd = float(np.sqrt(np.mean(np.sum((fitted - fixed) ** 2, axis=1))))
    return transformed_records, rmsd


def renumber_record(line, serial):
    return line[:6] + f"{serial:5d}" + line[11:]


def replace_chain(complex_path, variant_path, output_path, target_chain, variant_chain, excluded_ranges):
    variant_records, variant_residues = read_chain(variant_path, variant_chain)
    _, target_residues = read_chain(complex_path, target_chain)
    variant_records, rmsd = fit_variant(
        variant_records, target_residues, variant_residues, excluded_ranges
    )

    output_lines = []
    inserted = False
    complex_lines = complex_path.read_text().splitlines()
    target_ter = next(
        (
            line
            for line in complex_lines
            if line.startswith("TER   ") and line[21] == target_chain
        ),
        None,
    )
    for line in complex_lines:
        if line.startswith("TER   ") and line[21] == target_chain:
            continue
        if line.startswith(("ATOM  ", "HETATM")) and line[21] == target_chain:
            if not inserted:
                output_lines.extend(variant_records)
                inserted = True
                if target_ter is not None:
                    output_lines.append(target_ter)
            continue
        output_lines.append(line)
    if not inserted:
        raise ValueError(f"Chain {target_chain!r} was not found in {complex_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    serial = 1
    numbered_lines = []
    for line in output_lines:
        if line.startswith(("ATOM  ", "HETATM", "TER   ")):
            numbered_lines.append(renumber_record(line, serial))
            serial += 1
        else:
            numbered_lines.append(line)
    output_path.write_text("\n".join(numbered_lines) + "\n")
    return rmsd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variant_number", type=int)
    parser.add_argument("--complex", type=Path, default=DEFAULT_COMPLEX)
    parser.add_argument("--variant-pdb", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--target-chain", default="H")
    parser.add_argument("--variant-chain", default="A")
    parser.add_argument(
        "--exclude-ranges",
        default="29-34,94-114",
        help="Residue ranges excluded from alignment, e.g. 29-34,94-114",
    )
    args = parser.parse_args()

    variant_path = args.variant_pdb or (
        DEFAULT_VARIANT_DIR / f"test_{args.variant_number}.pdb"
    )
    output_path = args.output_dir / f"5UDC_HLF_variant_{args.variant_number}.pdb"
    rmsd = replace_chain(
        args.complex,
        variant_path,
        output_path,
        args.target_chain,
        args.variant_chain,
        parse_ranges(args.exclude_ranges),
    )
    print(f"Wrote {output_path}")
    print(f"Framework CA alignment RMSD: {rmsd:.3f} A")


if __name__ == "__main__":
    main()
