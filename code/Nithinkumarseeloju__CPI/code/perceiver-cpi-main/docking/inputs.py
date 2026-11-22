"""Clean a single protein sequence before scoring or docking."""
import re


def clean_sequence(text):
    lines = text.strip().splitlines()
    if lines and lines[0].lstrip().startswith(">"):
        lines = lines[1:]
    if any(line.lstrip().startswith(">") for line in lines):
        raise ValueError("Enter one FASTA record at a time.")
    sequence = re.sub(r"[\s\d]", "", "".join(lines)).upper()
    invalid = sorted(set(sequence) - set("ACDEFGHIKLMNPQRSTVWY"))
    if invalid:
        raise ValueError("Invalid amino-acid letters: " + ", ".join(invalid))
    if len(sequence) < 20:
        raise ValueError(f"Enter at least 20 amino acids (received {len(sequence)}).")
    return sequence
