#!/usr/bin/env python3
"""
check_top_vs_tpr.py -- does a GROMACS topology (.top/.itp) describe the same atoms as a .tpr?

Compares, atom by atom, residue name, atom name, charge and mass of the FIRST [ atoms ] block found in the
topology file with the first atoms of the .tpr (protein first, as in your systems).  If the counts differ it
aligns the two atom lists and prints exactly which atoms are present in the .tpr but missing from the
topology (or vice versa), e.g. the 11 atoms of the C-terminal Leu289.

Usage
-----
    python check_top_vs_tpr.py md.tpr rebuild_topol/topol_rebuilt.top
    python check_top_vs_tpr.py md.tpr topol_Protein_chain_A.itp
    python check_top_vs_tpr.py negative_control/v2_correct/md_negctrl.tpr negative_control/v2_correct/topol_Protein_chain_A.itp
    python check_top_vs_tpr.py md.tpr topology.itp --section-index 0     # which [ atoms ] block (0 = first)

Needs: numpy, MDAnalysis (the same environment as tp53_checks.py).  Read-only.
"""
import argparse
import difflib
import re
import sys


def read_atoms(path, section_index=0):
    """Return list of dicts for the requested [ atoms ] block (comments and blank lines skipped)."""
    blocks, cur, in_atoms = [], None, False
    with open(path, errors="replace") as fh:
        for raw in fh:
            line = raw.split(";")[0].strip()
            if not line:
                continue
            m = re.match(r"^\[\s*(\w+)\s*\]$", line)
            if m:
                in_atoms = m.group(1).lower() == "atoms"
                if in_atoms:
                    cur = []
                    blocks.append(cur)
                continue
            if in_atoms and not line.startswith("#"):
                f = line.split()
                if len(f) >= 7 and f[0].isdigit():
                    cur.append({"nr": int(f[0]), "type": f[1], "resnr": int(f[2]), "res": f[3], "name": f[4],
                                "charge": float(f[6]), "mass": float(f[7]) if len(f) > 7 else None})
    if not blocks:
        sys.exit(f"no [ atoms ] section found in {path}")
    if section_index >= len(blocks):
        sys.exit(f"only {len(blocks)} [ atoms ] block(s) in {path}")
    return blocks[section_index], len(blocks)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tpr")
    ap.add_argument("top")
    ap.add_argument("--section-index", type=int, default=0)
    ap.add_argument("--max-print", type=int, default=15)
    ap.add_argument("--select", default=None,
                    help='MDAnalysis selection of the tpr atoms the topology block describes (default: protein), '
                         'e.g. --select "resname UNL" for a ligand itp')
    ap.add_argument("--ignore-resname", action="store_true", help="compare atom names only (ligand itp residue names often differ)")
    ap.add_argument("--types", action="store_true", help="also compare the atom TYPE names (itp column 2) with the tpr (decides the LJ parameters)")
    a = ap.parse_args()

    import MDAnalysis as mda
    u = mda.Universe(a.tpr)
    atoms, nblocks = read_atoms(a.top, a.section_index)
    n_top = len(atoms)
    print(f"topology : {a.top}  ([ atoms ] block {a.section_index} of {nblocks}) -> {n_top} atoms")
    sel = a.select or "protein or resname HIE HID HIP HISE HISD CYM CYX ASH GLH LYN"
    prot = u.select_atoms(sel)
    print(f"tpr      : {a.tpr}  -> {len(u.atoms)} atoms in total, {len(prot)} atoms selected by \"{sel}\"")
    if len(prot) == 0:
        sys.exit("selection is empty")
    # compare against the first n_top atoms of the tpr
    tpr_first = prot[:n_top]
    rk = (lambda r: "") if a.ignore_resname else (lambda r: str(r).upper()[:3])
    key_top = [(rk(x["res"]), x["name"].upper()) for x in atoms]
    key_tpr = [(rk(r), str(n).upper()) for r, n in zip(tpr_first.resnames, tpr_first.names)]
    same_count = (n_top == len(prot))
    direct = [i for i, (p, q) in enumerate(zip(key_top, key_tpr)) if p != q]

    if same_count and not direct:
        print("\nRESULT: atom count and residue/atom names agree one-to-one with the selected .tpr atoms.")
        has_q = hasattr(u.atoms, "charges")
        has_m = hasattr(u.atoms, "masses")
        bad_q = bad_m = 0
        for x, at in zip(atoms, tpr_first):
            if has_q and abs(x["charge"] - float(at.charge)) > 2e-3:
                bad_q += 1
            if has_m and x["mass"] is not None and abs(x["mass"] - float(at.mass)) > 2e-2:
                bad_m += 1
        print(f"  charges: {'all within 0.002 e' if bad_q == 0 else str(bad_q) + ' atoms differ'}"
              f"   masses: {'all within 0.02' if bad_m == 0 else str(bad_m) + ' atoms differ'}")
        if a.types:
            if hasattr(u.atoms, "types"):
                bad_t = [(x["nr"], x["type"], str(at.type)) for x, at in zip(atoms, tpr_first)
                         if x["type"].upper() != str(at.type).upper()]
                print(f"  atom types: {'all identical' if not bad_t else str(len(bad_t)) + ' atoms differ, first: ' + str(bad_t[:5])}")
            else:
                print("  atom types: not available from this tpr via MDAnalysis")
        print(f"  net charge of the topology block: {sum(x['charge'] for x in atoms):+.3f} e")
        return

    print("\nRESULT: MISMATCH between topology and .tpr.")
    # align by (residue, atom) sequences to locate missing / extra atoms
    key_tpr_all = [(rk(r), str(n).upper()) for r, n in zip(prot.resnames, prot.names)]
    sm = difflib.SequenceMatcher(a=key_tpr_all, b=key_top, autojunk=False)
    shown = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("delete", "replace"):
            print(f"  in .tpr but NOT in the topology ({i2 - i1} atoms, tpr protein atom index {i1 + 1}-{i2}):")
            for at in prot[i1:i2][: a.max_print]:
                print(f"      {at.resname}{at.resid} {at.name}")
            shown += 1
        if tag in ("insert", "replace"):
            print(f"  in the topology but NOT in the .tpr ({j2 - j1} atoms, topology atom nr {j1 + 1}-{j2}):")
            for x in atoms[j1:j2][: a.max_print]:
                print(f"      {x['res']}{x['resnr']} {x['name']}")
            shown += 1
    if shown == 0:
        print("  atom counts differ, but the residue/atom name sequences are identical; compare charges/masses.")
    print(f"\n  net charge of the topology block: {sum(x['charge'] for x in atoms):+.3f} e")
    print("  A topology used with this .tpr (gmx_MMPBSA -cp, new simulations) must list exactly the .tpr atoms in the same order.")


if __name__ == "__main__":
    main()
