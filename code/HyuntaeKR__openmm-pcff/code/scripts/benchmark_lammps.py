"""LAMMPS speed on the relaxed benchmark systems (KOKKOS on the GPU, 1 MPI rank, 1 thread, 1 fs).

For each system and k-space style (pppm/cg 0.001, which has no KOKKOS version, and pppm 0.001, which runs as pppm/kk),
starting from the relaxed state (relax/relaxed.data, with velocities):
- NVE (fix nve), NVT (fix nvt, 300 K, Tdamp 100 fs), and NPT (fix npt, 300 K, 1 atm, Tdamp 100 fs, Pdamp 1000 fs, iso);
- each run: 1000 warm-up steps, then N_STEPS timed steps; ns/day is taken from LAMMPS's 'Performance:' line of the timed run.
The timing breakdown (Pair, Bond, Kspace, ...) is only accurate with CUDA_LAUNCH_BLOCKING=1 (LAMMPS doc/src/Speed_kokkos.rst),
which slows the run; it is collected in separate 'breakdown' runs and not used for ns/day.
Inputs and logs go to benchmark/<system>/lammps/<case>/.
Run from the repository root:

    python scripts/benchmark_lammps.py [system ...]
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_benchmark_systems import BENCHMARK_POLYMERS, LAMMPS_EXECUTABLE, LAMMPS_KOKKOS_ARGUMENTS, TEMPERATURE_K
from benchmark_tools import BENCHMARK_ROOT


N_WARMUP_STEPS = 1000
N_STEPS = 5000

KSPACE_STYLES = {"pppm_cg": "pppm/cg 0.001", "pppm": "pppm 0.001"}

ENSEMBLE_FIXES = {
    "nve": "fix\t\tintegration all nve",
    "nvt": f"fix\t\tintegration all nvt temp {TEMPERATURE_K} {TEMPERATURE_K} 100",
    "npt": f"fix\t\tintegration all npt temp {TEMPERATURE_K} {TEMPERATURE_K} 100 iso 1.0 1.0 1000",
}

TIMING_SECTIONS = ["Pair", "Bond", "Kspace", "Neigh", "Comm", "Output", "Modify", "Other"]


def write_input(case_directory: Path, name: str, kspace_command: str, ensemble: str) -> None:
    input_lines = [
        "# Speed benchmark, written by scripts/benchmark_lammps.py",
        "units\t\treal",
        "atom_style\tfull",
        "boundary\tp p p",
        "read_data\t../../relax/relaxed.data",
        f"include\t\t../../{name}.params",
        f"kspace_style\t{kspace_command}",
        "timestep\t1.0",
        ENSEMBLE_FIXES[ensemble],
        "thermo_style\tcustom step temp pe etotal press density",
        "thermo\t\t1000",
        f"run\t\t{N_WARMUP_STEPS}",
        f"run\t\t{N_STEPS}",
    ]
    (case_directory / "in.lmp").write_text("\n".join(input_lines) + "\n")


def read_last_run_timing(log_path: Path) -> dict:
    """Return ns/day and the timing breakdown (seconds) of the last run in a LAMMPS log."""
    text = log_path.read_text()

    performance = re.findall(r"Performance: ([0-9.eE+-]+) ns/day", text)
    loop_times = re.findall(r"Loop time of ([0-9.eE+-]+) on", text)

    breakdown_blocks = text.split("MPI task timing breakdown:")
    breakdown = {}
    for line in breakdown_blocks[-1].splitlines():
        fields = [field.strip() for field in line.split("|")]
        if fields and fields[0] in TIMING_SECTIONS:
            breakdown[fields[0]] = float(fields[2])

    return {"ns_per_day": float(performance[-1]), "loop_seconds": float(loop_times[-1]), "breakdown_seconds": breakdown}


def run_case(name: str, case: str, kspace_command: str, ensemble: str, launch_blocking: bool) -> dict:
    case_directory = BENCHMARK_ROOT / name / "lammps" / case
    case_directory.mkdir(parents=True, exist_ok=True)

    write_input(case_directory, name, kspace_command, ensemble)

    environment = dict(os.environ)
    if launch_blocking:
        environment["CUDA_LAUNCH_BLOCKING"] = "1"
    else:
        environment.pop("CUDA_LAUNCH_BLOCKING", None)

    subprocess.run(
        [str(LAMMPS_EXECUTABLE), *LAMMPS_KOKKOS_ARGUMENTS, "-in", "in.lmp", "-log", "log.lammps", "-screen", "none"],
        cwd=case_directory,
        env=environment,
        check=True,
    )

    return read_last_run_timing(case_directory / "log.lammps")


if __name__ == "__main__":
    names = sys.argv[1:] or list(BENCHMARK_POLYMERS)

    for name in names:
        results = {"n_steps": N_STEPS, "speed": {}, "breakdown": {}}

        for kspace_case, kspace_command in KSPACE_STYLES.items():
            for ensemble in ENSEMBLE_FIXES:
                case = f"{kspace_case}_{ensemble}"
                results["speed"][case] = run_case(name, case, kspace_command, ensemble, launch_blocking=False)

            # Accurate per-section times need CUDA_LAUNCH_BLOCKING=1; NVE only.
            case = f"{kspace_case}_nve_breakdown"
            results["breakdown"][case] = run_case(name, case, kspace_command, "nve", launch_blocking=True)

        (BENCHMARK_ROOT / name / "lammps" / "benchmark.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps({name: results}, indent=2))
