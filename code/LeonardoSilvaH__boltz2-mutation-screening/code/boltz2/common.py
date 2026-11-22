"""Shared helpers for the Boltz-2 co-folding pipeline over consolidated_projects.

Expected input layout (one directory per gene)::

    <root>/<GENE>/<DRUG>.sdf           ligands, shared by every variant of the gene
    <root>/<GENE>/wild-type/<X>.pdb    reference structure
    <root>/<GENE>/<VARIANT>/*.pdb      one modelled mutant per directory

Boltz-2 folds from *sequence*, not from a given structure, so the mutation has to
travel in the amino-acid sequence. The mutant PDBs carry no SEQRES records, so the
sequence is read back from the CA atoms of the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

WT_DIRNAME = "wild-type"
SEP = "__"

AA3TO1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    # a few modified residues that show up in predicted models
    "MSE": "M", "SEC": "U", "PYL": "O",
}


def sanitize(name: str) -> str:
    """Make a token safe for a filename and free of the ``__`` field separator."""
    token = re.sub(r"[^A-Za-z0-9.+-]", "-", name)
    return re.sub(r"-{2,}", "-", token).strip("-")


def extract_sequence(pdb_path: Path) -> tuple[str, str]:
    """Return ``(sequence, chain_id)`` for the first protein chain in *pdb_path*.

    Reads CA atoms only, keyed by (residue number, insertion code) so that
    alternate locations and duplicated atoms cannot inflate the sequence.
    """
    residues: dict[tuple[int, str], str] = {}
    order: list[tuple[int, str]] = []
    chain_id = ""
    for line in pdb_path.read_text().splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            if line.startswith("ENDMDL"):
                break  # first model only
            continue
        if line[12:16].strip() != "CA":
            continue
        altloc = line[16]
        if altloc not in (" ", "A"):
            continue
        chain = line[21]
        if not chain_id:
            chain_id = chain
        elif chain != chain_id:
            continue  # monomer models only; ignore any extra chains
        key = (int(line[22:26]), line[26])
        if key in residues:
            continue
        residues[key] = AA3TO1.get(line[17:20].strip(), "X")
        order.append(key)
    return "".join(residues[k] for k in order), chain_id or "A"


@dataclass(frozen=True)
class Variant:
    """One modelled structure: a wild-type or a single mutant of a gene."""

    gene: str
    name: str          # directory name, e.g. "pG328E" or "wild-type"
    pdb: Path
    sequence: str
    is_wt: bool

    @property
    def key(self) -> str:
        return f"{self.gene}{SEP}{sanitize(self.name)}"


@dataclass(frozen=True)
class Job:
    """One protein-variant x ligand co-folding job."""

    variant: Variant
    drug: str
    smiles: str

    @property
    def name(self) -> str:
        return f"{self.variant.key}{SEP}{sanitize(self.drug)}"


def load_variants(gene_dir: Path) -> tuple[Variant | None, list[Variant]]:
    """Return ``(wild_type, mutants)`` for one gene directory.

    A variant directory with no .pdb file is skipped silently; the caller is
    expected to run qc_structures.py to see those.
    """
    wt: Variant | None = None
    mutants: list[Variant] = []
    for sub in sorted(p for p in gene_dir.iterdir() if p.is_dir()):
        pdbs = sorted(sub.glob("*.pdb"))
        if not pdbs:
            continue
        # Prefer AlphaFold's top-ranked model when several are present.
        pdb = next((p for p in pdbs if p.stem == "ranked_0"), pdbs[0])
        sequence, _ = extract_sequence(pdb)
        if not sequence:
            continue
        variant = Variant(
            gene=gene_dir.name,
            name=sub.name,
            pdb=pdb,
            sequence=sequence,
            is_wt=sub.name == WT_DIRNAME,
        )
        if variant.is_wt:
            wt = variant
        else:
            mutants.append(variant)
    return wt, mutants


def load_ligands(gene_dir: Path) -> dict[str, str]:
    """Map drug name -> canonical SMILES for every .sdf at the top of *gene_dir*."""
    from rdkit import Chem, RDLogger

    RDLogger.DisableLog("rdApp.*")
    ligands: dict[str, str] = {}
    for sdf in sorted(gene_dir.glob("*.sdf")):
        mol = next(Chem.ForwardSDMolSupplier(str(sdf)), None)
        if mol is None:
            continue
        ligands[sdf.stem] = Chem.MolToSmiles(mol)
    return ligands


def iter_gene_dirs(root: Path) -> list[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir())


def iter_jobs(root: Path, genes: list[str] | None = None) -> list[Job]:
    """Enumerate every variant x ligand pair under *root*."""
    jobs: list[Job] = []
    for gene_dir in iter_gene_dirs(root):
        if genes and gene_dir.name not in genes:
            continue
        wt, mutants = load_variants(gene_dir)
        ligands = load_ligands(gene_dir)
        for variant in ([wt] if wt else []) + mutants:
            for drug, smiles in ligands.items():
                jobs.append(Job(variant=variant, drug=drug, smiles=smiles))
    return jobs


def parse_job_name(name: str) -> tuple[str, str, str]:
    """Inverse of ``Job.name``: ``GENE__VARIANT__DRUG`` -> the three fields."""
    parts = name.split(SEP)
    if len(parts) != 3:
        raise ValueError(f"cannot parse job name: {name!r}")
    return parts[0], parts[1], parts[2]
