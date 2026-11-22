"""Build the benchmark systems (about 50k atoms) with EMC and compress and relax them with LAMMPS.

EMC builds at a low density (0.5 g/cm^3, as the reference systems), because dense EMC builds are slow.
LAMMPS (KOKKOS on the GPU) then compresses the box to the target density and relaxes it.

For every system this writes, in benchmark/<system>/:
    input.esh, <system>.data, <system>.params      EMC build at 0.5 g/cm^3
    relax/in.lmp, relax/log.lammps                  LAMMPS compression and relaxation
    relax/relaxed.data                              LAMMPS write_data nocoeff at the end (positions, image flags, velocities)
    relax/relaxed_positions.dump                    unwrapped positions at the end, sorted by atom id

LAMMPS protocol (1 fs time step, pppm 0.001, i.e. pppm/kk under KOKKOS, 300 K):
1. energy minimization, then 1000 steps of Langevin + nve/limit 0.2 Angstrom (EMC's own start-up protocol, see EMC's <system>.in);
2. compression to the target density with fix deform (box lengths scaled by (0.5 / target density)^(1/3) linearly in time) under Langevin + nve;
3. 10 ps Nose-Hoover NVT at the target density.
The result is a stable configuration at the target density for timing, not an equilibrated state for property calculations.
Run from the repository root:

    python scripts/make_benchmark_systems.py [system ...]
"""

import subprocess
import sys
from pathlib import Path

from rdkit import Chem

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_emc_reference import run_emc, write_input_esh
from validation.reference_systems import POLYMERS, polymer_chain_smiles


BENCHMARK_ROOT = Path(__file__).resolve().parent.parent / "benchmark"
# LAMMPS executable with the KOKKOS package (GPU), found on PATH.
LAMMPS_EXECUTABLE = "lmp"

# KOKKOS on the GPU with 1 MPI rank and 1 thread; -sf kk selects the /kk variant of every style that has one.
LAMMPS_KOKKOS_ARGUMENTS = ["-k", "on", "g", "1", "t", "1", "-sf", "kk"]

N_REPEAT_UNITS = 50
TEMPERATURE_K = 300.0
SEED = 2026

# EMC build density, the same as the reference systems.
BUILD_DENSITY_G_CC = 0.5

# Length of the compression stage (1 fs steps).
COMPRESSION_STEPS = 50000

BENCHMARK_POLYMERS = {
    "polystyrene_50k": {"polymer": "polystyrene", "n_chains": 62, "density_g_cc": 1.05},
    "pmma_50k": {"polymer": "pmma", "n_chains": 66, "density_g_cc": 1.20},
}


def emc_system(name: str) -> dict:
    """Return the EMC_SYSTEMS-style description of one benchmark polymer (same chemistry as the reference oligomers)."""
    benchmark = BENCHMARK_POLYMERS[name]
    polymer = POLYMERS[benchmark["polymer"]]

    chain_smiles = polymer_chain_smiles(polymer["head"][1], polymer["repeat"][1], N_REPEAT_UNITS, polymer["tail"][1])
    n_atoms_per_chain = Chem.AddHs(Chem.MolFromSmiles(chain_smiles)).GetNumAtoms()

    return {
        "kind": "polymer",
        "description": f"Benchmark, {N_REPEAT_UNITS} repeat units {polymer['repeat'][0]}, {benchmark['n_chains']} chains, built at {BUILD_DENSITY_G_CC} g/cc and compressed to {benchmark['density_g_cc']} g/cc in LAMMPS.",
        "repeat_group": polymer["repeat"][0],
        "end_groups": {"head": (polymer["head"][0], 1), "tail": (polymer["tail"][0], 2)},
        "n_repeat_units": N_REPEAT_UNITS,
        "n_atoms_total": benchmark["n_chains"] * n_atoms_per_chain,
    }


def relax_with_lammps(name: str, system_directory: Path, target_density_g_cc: float) -> None:
    relax_directory = system_directory / "relax"
    relax_directory.mkdir(exist_ok=True)

    # Mass is conserved, so the box length scales with density^(-1/3).
    box_scale_factor = (BUILD_DENSITY_G_CC / target_density_g_cc) ** (1.0 / 3.0)

    input_lines = [
        "# Compression and relaxation of the EMC build, written by scripts/make_benchmark_systems.py",
        "units\t\treal",
        "atom_style\tfull",
        "boundary\tp p p",
        f"read_data\t../{name}.data",
        f"include\t\t../{name}.params",
        "kspace_style\tpppm 0.001",
        "thermo_style\tcustom step temp pe ebond eangle evdwl ecoul elong press density",
        "thermo\t\t1000",
        "",
        "# 1. Remove close contacts of the EMC build.",
        "minimize\t1.0e-4 1.0e-6 1000 10000",
        "reset_timestep\t0",
        "timestep\t1.0",
        f"velocity\tall create {TEMPERATURE_K} {SEED} dist gaussian rot yes mom yes",
        f"fix\t\ttemperature all langevin {TEMPERATURE_K} {TEMPERATURE_K} 100 {SEED}",
        "fix\t\tintegration all nve/limit 0.2",
        "run\t\t1000",
        "unfix\t\tintegration",
        "",
        f"# 2. Compress from {BUILD_DENSITY_G_CC} to {target_density_g_cc} g/cm^3 (box lengths x {box_scale_factor:.6f}).",
        "fix\t\tintegration all nve",
        f"fix\t\tcompression all deform 1 x scale {box_scale_factor:.10f} y scale {box_scale_factor:.10f} z scale {box_scale_factor:.10f} remap x",
        f"run\t\t{COMPRESSION_STEPS}",
        "unfix\t\tcompression",
        "unfix\t\tintegration",
        "unfix\t\ttemperature",
        "",
        "# 3. Nose-Hoover NVT at the target density.",
        f"fix\t\tnvt all nvt temp {TEMPERATURE_K} {TEMPERATURE_K} 100",
        "run\t\t10000",
        "",
        "write_data\trelaxed.data nocoeff",
        "write_dump\tall custom relaxed_positions.dump id xu yu zu modify sort id format float %.10g",
    ]

    (relax_directory / "in.lmp").write_text("\n".join(input_lines) + "\n")

    subprocess.run(
        [str(LAMMPS_EXECUTABLE), *LAMMPS_KOKKOS_ARGUMENTS, "-in", "in.lmp", "-log", "log.lammps", "-screen", "none"],
        cwd=relax_directory,
        check=True,
    )


if __name__ == "__main__":
    names = sys.argv[1:] or list(BENCHMARK_POLYMERS)

    for name in names:
        system_directory = BENCHMARK_ROOT / name
        system_directory.mkdir(parents=True, exist_ok=True)

        write_input_esh(
            name,
            emc_system(name),
            system_directory,
            BUILD_DENSITY_G_CC,
            script="scripts/make_benchmark_systems.py",
            purpose="benchmark",
        )
        run_emc(name, system_directory)
        print(f"{name}: EMC build done")

        relax_with_lammps(name, system_directory, BENCHMARK_POLYMERS[name]["density_g_cc"])
        print(f"{name}: LAMMPS compression and relaxation done")
