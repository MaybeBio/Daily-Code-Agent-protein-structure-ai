import subprocess
import sys
from pathlib import Path

import pandas as pd


def test_export_fasta_uses_lf_line_endings(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "proteins.csv"
    output_path = tmp_path / "proteins.fasta"

    dataframe = pd.DataFrame(
        {
            "accession": [
                "P00001",
                "P00002",
            ],
            "sequence": [
                "ACDEFG",
                "HIKLMN",
            ],
        }
    )

    dataframe.to_csv(
        input_path,
        index=False,
    )

    repository_root = (
        Path(__file__).resolve().parents[1]
    )

    script_path = (
        repository_root
        / "scripts"
        / "export_fasta.py"
    )

    subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )

    raw = output_path.read_bytes()

    assert b"\r" not in raw

    assert raw == (
        b">P00001\n"
        b"ACDEFG\n"
        b">P00002\n"
        b"HIKLMN\n"
    )