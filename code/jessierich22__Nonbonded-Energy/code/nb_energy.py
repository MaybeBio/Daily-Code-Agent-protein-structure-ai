#!/usr/bin/env python3

import argparse
import os
import re
import math
import numpy as np
import MDAnalysis as mda
from MDAnalysis.lib.distances import capped_distance


# ============================================================
# CONSTANTS
# ============================================================

K_COUL = 138.935456  # kJ mol^-1 nm e^-2

# ============================================================
# ARGUMENTS
# ============================================================

def parse_args():

    parser = argparse.ArgumentParser(
        description=(
            "Calculate LJ-SR and Coulomb-SR between "
            "two MDAnalysis selections."
        )
    )

    parser.add_argument(
        "-s", "--structure",
        required=True,
        help="GROMACS TPR"
    )

    parser.add_argument(
        "-f", "--trajectory",
        required=True,
        help="Trajectory (XTC/TRR)"
    )

    parser.add_argument(
        "-p", "--topology",
        required=True,
        help="GROMACS topol.top"
    )

    parser.add_argument(
        "--ff-dir",
        default=None,
        help=(
            "Optional force-field directory used to resolve topology "
            "includes that cannot be found relative to the TOP/ITP files."
        )
    )

    parser.add_argument(
        "--sel1",
        required=True,
        help="MDAnalysis selection 1"
    )

    parser.add_argument(
        "--sel2",
        required=True,
        help="MDAnalysis selection 2"
    )

    parser.add_argument(
        "--rcoulomb",
        type=float,
        default=1.2,
        help="Coulomb cutoff in nm (default: 1.2)"
    )

    parser.add_argument(
        "--ewald-rtol",
        type=float,
        default=1e-5,
        help="Ewald relative tolerance for PME real-space term (default: 1e-5)"
    )

    parser.add_argument(
        "--rvdw",
        type=float,
        default=1.2,
        help="LJ cutoff in nm (default: 1.2)"
    )

    parser.add_argument(
        "--top-pairs",
        type=int,
        default=0,
        help=(
            "Print N pairs with largest absolute "
            "nonbonded contribution per frame"
        )
    )

    parser.add_argument(
        "-o", "--output",
        default="energy.xvg",
        help="Output XVG"
    )

    return parser.parse_args()


# ============================================================
# TOPOLOGY READER
# ============================================================

def read_top_recursive(filename, ff_dir=None, visited=None):

    if visited is None:
        visited = set()

    filename = os.path.abspath(filename)

    if ff_dir is not None:
        ff_dir = os.path.abspath(ff_dir)

    if filename in visited:
        return []

    visited.add(filename)

    if not os.path.isfile(filename):
        raise FileNotFoundError(
            f"Topology/include not found: {filename}"
        )

    lines = []
    basedir = os.path.dirname(filename)

    with open(filename) as f:

        for raw in f:

            stripped = raw.strip()

            match = re.match(
                r'^\s*#include\s+["<](.*?)[">]',
                stripped
            )

            # Normal topology line
            if not match:
                lines.append(raw)
                continue

            inc = match.group(1)
            found = None

            # ------------------------------------------------
            # 1. Relative to the current TOP/ITP file
            # ------------------------------------------------

            candidate = os.path.abspath(
                os.path.join(
                    basedir,
                    inc
                )
            )

            if os.path.isfile(candidate):
                found = candidate

            # ------------------------------------------------
            # 2. Search inside the user-provided FF directory
            # ------------------------------------------------

            if found is None and ff_dir is not None:

                candidate = os.path.join(
                    ff_dir,
                    inc
                )

                if os.path.isfile(candidate):
                    found = candidate

            # ------------------------------------------------
            # 3. Handle includes containing the FF directory
            #
            # Example:
            # #include "charmm36-jul2022.ff/forcefield.itp"
            #
            # with:
            # --ff-dir /path/to/charmm36-jul2022.ff
            # ------------------------------------------------

            if found is None and ff_dir is not None:

                ff_name = os.path.basename(
                    os.path.normpath(ff_dir)
                )

                prefix = ff_name + "/"

                if inc.startswith(prefix):

                    relative_name = inc[len(prefix):]

                    candidate = os.path.join(
                        ff_dir,
                        relative_name
                    )

                    if os.path.isfile(candidate):
                        found = candidate

            # ------------------------------------------------
            # Include found
            # ------------------------------------------------

            if found is not None:

                print(
                    f"Include: {inc}\n"
                    f"      -> {found}"
                )

                lines.extend(
                    read_top_recursive(
                        found,
                        ff_dir=ff_dir,
                        visited=visited
                    )
                )

                continue

            # ------------------------------------------------
            # Missing position restraints can be ignored
            # ------------------------------------------------

            basename = os.path.basename(inc)

            if basename.startswith("posre"):

                print(
                    f"Ignoring missing position "
                    f"restraint: {inc}"
                )

                continue

            # ------------------------------------------------
            # Other missing includes deserve a warning
            # ------------------------------------------------

            print(
                f"WARNING: include not found: {inc}"
            )

    return lines


# ============================================================
# TOPOLOGY PARSER
# ============================================================

def clean_line(line):

    # Remove GROMACS comments
    return line.split(";", 1)[0].strip()


def parse_topology(lines):

    section = None

    defaults = None

    atomtypes = {}

    nonbond = {}

    for raw in lines:

        line = clean_line(raw)

        if not line:
            continue

        # Skip preprocessor directives
        if line.startswith("#"):
            continue

        # ----------------------------------------------------
        # Section
        # ----------------------------------------------------

        if line.startswith("["):

            section = line.strip(
                "[] "
            ).lower()

            continue

        fields = line.split()

        # ----------------------------------------------------
        # [ defaults ]
        #
        # nbfunc comb-rule gen-pairs fudgeLJ fudgeQQ
        # ----------------------------------------------------

        if section == "defaults":

            if defaults is None and len(fields) >= 2:

                defaults = {
                    "nbfunc": int(fields[0]),
                    "comb_rule": int(fields[1])
                }

                if len(fields) >= 3:
                    defaults["gen_pairs"] = fields[2]

                if len(fields) >= 4:
                    defaults["fudgeLJ"] = float(fields[3])

                if len(fields) >= 5:
                    defaults["fudgeQQ"] = float(fields[4])

        # ----------------------------------------------------
        # [ atomtypes ]
        #
        # We need the last two columns.
        #
        # comb-rule 1:
        #     C6 C12
        #
        # comb-rule 2/3:
        #     sigma epsilon
        # ----------------------------------------------------

        elif section == "atomtypes":

            if len(fields) < 3:
                continue

            atomtype = fields[0]

            try:

                V = float(fields[-2])
                W = float(fields[-1])

            except ValueError:

                continue

            atomtypes[atomtype] = (
                V,
                W
            )

        # ----------------------------------------------------
        # [ nonbond_params ]
        #
        # i j func V W
        # ----------------------------------------------------

        elif section == "nonbond_params":

            if len(fields) < 5:
                continue

            type1 = fields[0]
            type2 = fields[1]

            try:

                func = int(fields[2])
                V = float(fields[3])
                W = float(fields[4])

            except ValueError:

                continue

            nonbond[
                (type1, type2)
            ] = (
                func,
                V,
                W
            )

            nonbond[
                (type2, type1)
            ] = (
                func,
                V,
                W
            )

    # ========================================================
    # Validation
    # ========================================================

    if defaults is None:

        raise RuntimeError(
            "[ defaults ] not found."
        )

    if len(atomtypes) == 0:

        raise RuntimeError(
            "No [ atomtypes ] found."
        )

    return (
        defaults,
        atomtypes,
        nonbond
    )


# ============================================================
# LJ COMBINATION RULE
# ============================================================

def get_pair_lj(
    type1,
    type2,
    defaults,
    atomtypes,
    nonbond
):

    comb_rule = defaults["comb_rule"]

    # --------------------------------------------------------
    # Explicit [ nonbond_params ] has priority
    # --------------------------------------------------------

    if (type1, type2) in nonbond:

        func, V, W = nonbond[
            (type1, type2)
        ]

        if func != 1:

            raise RuntimeError(
                f"Unsupported nonbond function "
                f"for {type1}-{type2}: {func}"
            )

        if comb_rule == 1:

            return (
                "c6c12",
                V,
                W
            )

        return (
            "sigmaepsilon",
            V,
            W
        )

    # --------------------------------------------------------
    # Normal atom types
    # --------------------------------------------------------

    if type1 not in atomtypes:

        raise KeyError(
            f"Atom type '{type1}' "
            f"not found in [ atomtypes ]."
        )

    if type2 not in atomtypes:

        raise KeyError(
            f"Atom type '{type2}' "
            f"not found in [ atomtypes ]."
        )

    V1, W1 = atomtypes[type1]
    V2, W2 = atomtypes[type2]

    # --------------------------------------------------------
    # Combination rule 1
    #
    # C6/C12 geometric
    # --------------------------------------------------------

    if comb_rule == 1:

        C6 = np.sqrt(
            V1 * V2
        )

        C12 = np.sqrt(
            W1 * W2
        )

        return (
            "c6c12",
            C6,
            C12
        )

    # --------------------------------------------------------
    # Combination rule 2
    #
    # sigma arithmetic
    # epsilon geometric
    # --------------------------------------------------------

    elif comb_rule == 2:

        sigma = (
            V1 + V2
        ) / 2.0

        epsilon = np.sqrt(
            W1 * W2
        )

        return (
            "sigmaepsilon",
            sigma,
            epsilon
        )

    # --------------------------------------------------------
    # Combination rule 3
    #
    # sigma geometric
    # epsilon geometric
    # --------------------------------------------------------

    elif comb_rule == 3:

        sigma = np.sqrt(
            V1 * V2
        )

        epsilon = np.sqrt(
            W1 * W2
        )

        return (
            "sigmaepsilon",
            sigma,
            epsilon
        )

    raise RuntimeError(
        f"Unsupported combination rule: {comb_rule}"
    )


# ============================================================
# PME / EWALD REAL-SPACE COULOMB
# ============================================================

def ewald_beta_from_rtol(rcoulomb, ewald_rtol):
    """
    Reproduce the Ewald real-space splitting coefficient beta
    from rcoulomb and ewald_rtol by solving:

        erfc(beta * rcoulomb) = ewald_rtol

    Units:
        rcoulomb : nm
        beta     : nm^-1
    """
    if rcoulomb <= 0.0:
        raise ValueError("rcoulomb must be > 0.")
    if not (0.0 < ewald_rtol < 1.0):
        raise ValueError("ewald-rtol must be between 0 and 1.")

    # Robust bisection; avoids a SciPy dependency.
    lo = 0.0
    hi = 1.0

    while math.erfc(hi) > ewald_rtol:
        hi *= 2.0

    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if math.erfc(mid) > ewald_rtol:
            lo = mid
        else:
            hi = mid

    x = 0.5 * (lo + hi)
    return x / rcoulomb


# ============================================================
# MAIN
# ============================================================

def main():

    args = parse_args()

    # ========================================================
    # Read topology
    # ========================================================

    print()
    print("Reading GROMACS topology...")
    print()

    if args.ff_dir is not None:

        args.ff_dir = os.path.abspath(
            args.ff_dir
        )

        if not os.path.isdir(args.ff_dir):

            raise RuntimeError(
                f"Force-field directory does not exist:\n"
                f"{args.ff_dir}"
            )

        print(
            f"Force-field directory:\n"
            f"  {args.ff_dir}"
        )

    else:

        print(
            "Force-field directory: not specified\n"
            "Topology includes will be resolved relative "
            "to the TOP/ITP files."
        )

    print()

    topology_lines = read_top_recursive(
        args.topology,
        ff_dir=args.ff_dir
    )

    defaults, atomtypes, nonbond = (
        parse_topology(
            topology_lines
        )
    )

    print()
    print("==============================")
    print("Topology information")
    print("==============================")

    print(
        f"nbfunc           : "
        f"{defaults['nbfunc']}"
    )

    print(
        f"comb-rule        : "
        f"{defaults['comb_rule']}"
    )

    if "gen_pairs" in defaults:

        print(
            f"gen-pairs        : "
            f"{defaults['gen_pairs']}"
        )

    if "fudgeLJ" in defaults:

        print(
            f"fudgeLJ          : "
            f"{defaults['fudgeLJ']}"
        )

    if "fudgeQQ" in defaults:

        print(
            f"fudgeQQ          : "
            f"{defaults['fudgeQQ']}"
        )

    print(
        f"Atom types       : "
        f"{len(atomtypes)}"
    )

    print(
        f"Explicit NB pairs: "
        f"{len(nonbond) // 2}"
    )

    # ========================================================
    # MDAnalysis
    # ========================================================

    print()
    print("==============================")
    print("Loading TPR / trajectory")
    print("==============================")
    print()

    u = mda.Universe(
        args.structure,
        args.trajectory
    )

    A = u.select_atoms(
        args.sel1
    )

    B = u.select_atoms(
        args.sel2
    )

    if len(A) == 0:

        raise RuntimeError(
            "Selection 1 contains zero atoms."
        )

    if len(B) == 0:

        raise RuntimeError(
            "Selection 2 contains zero atoms."
        )

    print(
        f"Selection A:\n"
        f"  {args.sel1}"
    )

    print(
        f"  atoms = {len(A)}"
    )

    print()

    print(
        f"Selection B:\n"
        f"  {args.sel2}"
    )

    print(
        f"  atoms = {len(B)}"
    )

    # ========================================================
    # Charges / types from TPR
    # ========================================================

    try:

        charges_A = np.asarray(
            A.charges,
            dtype=float
        )

        charges_B = np.asarray(
            B.charges,
            dtype=float
        )

    except Exception as exc:

        raise RuntimeError(
            "Could not obtain atomic charges "
            "from TPR."
        ) from exc

    try:

        types_A = np.asarray(
            A.types,
            dtype=str
        )

        types_B = np.asarray(
            B.types,
            dtype=str
        )

    except Exception as exc:

        raise RuntimeError(
            "Could not obtain atom types "
            "from TPR."
        ) from exc

    print()
    print(
        f"Total charge A = "
        f"{charges_A.sum():.6f} e"
    )

    print(
        f"Total charge B = "
        f"{charges_B.sum():.6f} e"
    )

    # ========================================================
    # Check types
    # ========================================================

    unique_A = np.unique(
        types_A
    )

    unique_B = np.unique(
        types_B
    )

    print()
    print(
        f"Unique atom types A: "
        f"{len(unique_A)}"
    )

    print(
        f"Unique atom types B: "
        f"{len(unique_B)}"
    )

    # ========================================================
    # Precalculate LJ parameters
    # ========================================================

    print()
    print("Preparing LJ pair parameters...")

    lj_parameters = {}

    for type_A in unique_A:

        for type_B in unique_B:

            lj_parameters[
                (type_A, type_B)
            ] = get_pair_lj(
                type_A,
                type_B,
                defaults,
                atomtypes,
                nonbond
            )

    print(
        f"{len(lj_parameters)} "
        f"type-pair combinations prepared."
    )

    # ========================================================
    # PME real-space electrostatics
    # ========================================================

    beta = ewald_beta_from_rtol(
        args.rcoulomb,
        args.ewald_rtol
    )

    print()
    print("PME real-space Coulomb")
    print("----------------------")
    print(f"rcoulomb   : {args.rcoulomb} nm")
    print(f"ewald-rtol : {args.ewald_rtol:g}")
    print(f"beta       : {beta:.8f} nm^-1")

    # ========================================================
    # Cutoff
    # ========================================================

    max_cutoff_nm = max(
        args.rcoulomb,
        args.rvdw
    )

    # MDAnalysis uses Angstrom internally
    max_cutoff_A = (
        max_cutoff_nm * 10.0
    )

    # ========================================================
    # OUTPUT
    # ========================================================

    print()
    print("==============================")
    print("Calculating energies")
    print("==============================")
    print()

    with open(
        args.output,
        "w"
    ) as output:

        output.write(
            "# Nonbonded interaction energy\n"
        )

        output.write(
            f"# Selection A: {args.sel1}\n"
        )

        output.write(
            f"# Selection B: {args.sel2}\n"
        )

        output.write(
            f"# rvdw: {args.rvdw} nm\n"
        )

        output.write(
            f"# rcoulomb: "
            f"{args.rcoulomb} nm\n"
        )

        output.write(
            f"# electrostatics: PME/Ewald real-space erfc(beta*r)/r\n"
        )

        output.write(
            f"# ewald-rtol: {args.ewald_rtol:g}\n"
        )

        output.write(
            f"# beta: {beta:.10f} nm^-1\n"
        )

        output.write(
            "# time(ps) "
            "LJ-SR(kJ/mol) "
            "Coulomb-SR(kJ/mol) "
            "Total(kJ/mol)\n"
        )

        # ====================================================
        # Frames
        # ====================================================

        for ts in u.trajectory:

            pairs, distances_A = (
                capped_distance(
                    A.positions,
                    B.positions,
                    max_cutoff=max_cutoff_A,
                    box=ts.dimensions,
                    return_distances=True
                )
            )

            if len(pairs) == 0:

                lj_total = 0.0
                coul_total = 0.0

                output.write(
                    f"{ts.time:12.3f} "
                    f"{lj_total:18.6f} "
                    f"{coul_total:18.6f} "
                    f"{0.0:18.6f}\n"
                )

                continue

            # Angstrom -> nm
            distances_nm = (
                distances_A * 0.1
            )

            lj_total = 0.0
            coul_total = 0.0

            pair_results = []

            # =================================================
            # Individual atom pairs
            # =================================================

            for k in range(len(pairs)):

                ia = pairs[k, 0]
                ib = pairs[k, 1]

                r = distances_nm[k]

                if r <= 0.0:
                    continue

                atom_A = A[ia]
                atom_B = B[ib]

                type_A = types_A[ia]
                type_B = types_B[ib]

                # =============================================
                # LJ
                # =============================================

                lj = 0.0

                if r <= args.rvdw:

                    mode, P1, P2 = (
                        lj_parameters[
                            (type_A, type_B)
                        ]
                    )

                    if mode == "sigmaepsilon":

                        sigma = P1
                        epsilon = P2

                        sr = sigma / r

                        sr6 = sr ** 6

                        lj = (
                            4.0
                            * epsilon
                            * (
                                sr6 ** 2
                                - sr6
                            )
                        )

                    elif mode == "c6c12":

                        C6 = P1
                        C12 = P2

                        r6 = r ** 6
                        r12 = r6 ** 2

                        lj = (
                            C12 / r12
                            - C6 / r6
                        )

                # =============================================
                # Coulomb
                # =============================================

                coul = 0.0

                if r <= args.rcoulomb:

                    coul = (
                        K_COUL
                        * charges_A[ia]
                        * charges_B[ib]
                        * math.erfc(beta * r)
                        / r
                    )

                # =============================================
                # Accumulate
                # =============================================

                lj_total += lj
                coul_total += coul

                if args.top_pairs > 0:

                    pair_results.append(
                        (
                            abs(lj + coul),
                            lj,
                            coul,
                            r,
                            atom_A,
                            atom_B,
                            type_A,
                            type_B
                        )
                    )

            total = (
                lj_total
                + coul_total
            )

            # =================================================
            # Write XVG
            # =================================================

            output.write(
                f"{ts.time:12.3f} "
                f"{lj_total:18.6f} "
                f"{coul_total:18.6f} "
                f"{total:18.6f}\n"
            )

            print(
                f"\r"
                f"Frame {ts.frame:6d} | "
                f"t={ts.time:12.1f} ps | "
                f"LJ={lj_total:14.3f} | "
                f"Coul={coul_total:14.3f} | "
                f"Total={total:14.3f}",
                end="",
                flush=True
            )

            # =================================================
            # Print largest pair contributions
            # =================================================

            if args.top_pairs > 0:

                pair_results.sort(
                    key=lambda x: x[0],
                    reverse=True
                )

                print()

                print(
                    f"\nTop {args.top_pairs} "
                    f"pairs at frame {ts.frame}"
                )

                print(
                    "-" * 100
                )

                for result in pair_results[
                    :args.top_pairs
                ]:

                    (
                        _,
                        lj,
                        coul,
                        r,
                        atom_A,
                        atom_B,
                        type_A,
                        type_B
                    ) = result

                    print(
                        f"A "
                        f"{atom_A.index:7d} "
                        f"{atom_A.resname:5s} "
                        f"{atom_A.resid:5d} "
                        f"{atom_A.name:5s} "
                        f"{type_A:8s}"
                        f" <-> "
                        f"B "
                        f"{atom_B.index:7d} "
                        f"{atom_B.resname:5s} "
                        f"{atom_B.resid:5d} "
                        f"{atom_B.name:5s} "
                        f"{type_B:8s} "
                        f"r={r:7.4f} nm "
                        f"LJ={lj:14.3f} "
                        f"Coul={coul:14.3f} "
                        f"Sum={lj+coul:14.3f}"
                    )

    print()
    print()
    print(
        f"Finished.\n"
        f"Output: {args.output}"
    )


if __name__ == "__main__":
    main()
