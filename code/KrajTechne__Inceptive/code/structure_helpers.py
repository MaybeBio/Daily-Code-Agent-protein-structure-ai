"""Helpers to clean up target structures (.cif / .pdb) before giving them to BindCraft2.

Command line (runs on your computer, no Modal needed):

    # list residues that have insertion codes (BindCraft2 refuses to load these)
    python structure_helpers.py check inputs/targets/my_target.cif

    # renumber every chain 1..N, remove insertion codes, and convert your hotspots/coldspots
    # (written in the OLD numbering) to the new numbering
    python structure_helpers.py renumber inputs/targets/my_target.cif \\
        --out inputs/targets/my_target_1idx.cif --start 1 --chain A \\
        --coldspots "11-25,55-67" --hotspots "54,56"

Or import the functions from another script. Reading structures reuses Optimus's
extract_atom_array (optimus/StrucTools.py).
"""
import argparse
import os
import sys

import biotite.structure as struc
import biotite.structure.io.pdbx as pdbx
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "optimus"))
from StrucTools import extract_atom_array  # noqa: E402  (from the Optimus submodule)

THREE_TO_ONE = {"ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q", "GLU": "E",
                "GLY": "G", "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F",
                "PRO": "P", "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V"}


def find_insertion_codes(path):
    """Return the residues that carry an insertion code, e.g. ['A 122A', 'A 122B', ...]."""
    atoms = extract_atom_array(path)
    starts = struc.get_residue_starts(atoms)
    return [f"{atoms.chain_id[s]} {atoms.res_id[s]}{atoms.ins_code[s]}"
            for s in starts if atoms.ins_code[s] not in ("", "?")]


def renumber_structure(in_path, out_path, start=1):
    """Renumber the residues of every chain start, start+1, ... in file order; clear insertion codes.

    Chains keep their IDs. Returns {(chain, old_res_id, old_ins_code): new_res_id} so that
    residue numbers written for the old file can be converted (see remap_ranges).
    """
    atoms = extract_atom_array(in_path)
    starts = list(struc.get_residue_starts(atoms)) + [atoms.array_length()]
    new_ids = np.zeros(atoms.array_length(), dtype=int)
    mapping, next_id = {}, {}
    for begin, end in zip(starts[:-1], starts[1:]):
        chain = str(atoms.chain_id[begin])
        next_id[chain] = next_id.get(chain, start - 1) + 1
        new_ids[begin:end] = next_id[chain]
        ins = str(atoms.ins_code[begin])
        mapping[(chain, int(atoms.res_id[begin]), "" if ins == "?" else ins)] = next_id[chain]
    atoms.res_id = new_ids
    atoms.ins_code[:] = ""
    cif = pdbx.CIFFile()
    pdbx.set_structure(cif, atoms)
    cif.write(out_path)
    return mapping


def remap_ranges(ranges, mapping, chain):
    """Convert '11-25,55-67,99' written in the old numbering to the new numbering.

    Both ends of every range must be ordinary residues (no insertion code) of `chain`.
    """
    converted = []
    for part in ranges.split(","):
        part = part.strip()
        if not part:
            continue
        low, _, high = part.partition("-")
        new = []
        for old in (low, high or low):
            key = (chain, int(old), "")
            if key not in mapping:
                raise ValueError(f"Residue {chain} {old} is not an ordinary residue of the old file")
            new.append(mapping[key])
        converted.append(f"{new[0]}-{new[1]}" if high else str(new[0]))
    return ",".join(converted)


def range_sequence(path, chain, ranges):
    """One-letter sequence of each range, to check that two numberings select the same residues."""
    atoms = extract_atom_array(path)
    residues = {}
    for s in struc.get_residue_starts(atoms):
        if atoms.chain_id[s] == chain:
            residues[int(atoms.res_id[s])] = THREE_TO_ONE.get(str(atoms.res_name[s]), "X")
    out = []
    for part in ranges.split(","):
        low, _, high = part.strip().partition("-")
        out.append("".join(residues[r] for r in range(int(low), int(high or low) + 1)))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="list residues with insertion codes")
    check.add_argument("structure")

    renum = sub.add_parser("renumber", help="renumber residues and convert hotspots/coldspots")
    renum.add_argument("structure")
    renum.add_argument("--out", required=True, help="output .cif file (the input is not changed)")
    renum.add_argument("--start", type=int, default=1, help="first residue number (default 1)")
    renum.add_argument("--chain", default="A", help="chain the hotspots/coldspots refer to")
    renum.add_argument("--hotspots", default="")
    renum.add_argument("--coldspots", default="")
    args = parser.parse_args()

    if args.command == "check":
        found = find_insertion_codes(args.structure)
        print(f"{len(found)} residues with insertion codes" + (f": {', '.join(found)}" if found else ""))
        return

    mapping = renumber_structure(args.structure, args.out, args.start)
    print(f"Wrote {args.out} (residues numbered from {args.start}, insertion codes removed)")
    for label, ranges in (("hotspots", args.hotspots), ("coldspots", args.coldspots)):
        if not ranges:
            continue
        new_ranges = remap_ranges(ranges, mapping, args.chain)
        same = range_sequence(args.structure, args.chain, ranges) == range_sequence(args.out, args.chain, new_ranges)
        print(f'{label}: "{ranges}" -> "{new_ranges}"   same residues selected: {same}')


if __name__ == "__main__":
    main()
