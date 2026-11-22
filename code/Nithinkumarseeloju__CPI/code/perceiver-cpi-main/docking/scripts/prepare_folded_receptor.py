"""Prepare the standard, unmodified single-chain protein emitted by ESMFold."""
from pathlib import Path
import sys

from meeko import MoleculePreparation, PDBQTWriterLegacy, Polymer
from meeko.polymer import find_inter_mols_bonds


def prepare(folder):
    pdb = (folder / "protein.pdb").read_text()
    residues = Polymer._pdb_to_residue_mols(pdb, None, None)
    mols = {key: (mol, name) for key, (mol, name, _, _) in residues.items() if mol is not None}
    excluded_links = []
    for (left, right), pairs in find_inter_mols_bonds(mols).items():
        allowed = []
        for i, j in pairs:
            a = mols[left][0].GetAtomWithIdx(int(i)).GetPDBResidueInfo()
            b = mols[right][0].GetAtomWithIdx(int(j)).GetPDBResidueInfo()
            names = (a.GetName().strip(), b.GetName().strip())
            step = b.GetResidueNumber() - a.GetResidueNumber()
            peptide = (step, names) in ((1, ("C", "N")), (-1, ("N", "C")))
            disulfide = mols[left][1] == mols[right][1] == "CYS" and names == ("SG", "SG")
            allowed.append(peptide or disulfide)
        if not all(allowed):
            if len(pairs) != 1:
                raise ValueError(f"Ambiguous covalent links in the predicted coordinates between {left} and {right}.")
            excluded_links.append((left, right))
            print(f"Predicted inter-residue clash: {left} {right}", flush=True)

    polymer = Polymer.from_pdb_string(pdb, mk_prep=MoleculePreparation(compute_charges=False),
                                      bonds_to_delete=excluded_links, allow_bad_res=False)
    rigid, _ = PDBQTWriterLegacy.write_from_polymer(polymer)
    expected = {line[17:27] for line in pdb.splitlines() if line.startswith("ATOM  ")}
    prepared = {line[17:27] for line in rigid.splitlines() if line.startswith("ATOM  ")}
    if expected != prepared:
        raise ValueError(f"Prepared receptor residue mismatch: {sorted(expected.symmetric_difference(prepared))}")
    (folder / "receptor.pdbqt").write_text(rigid)


if __name__ == "__main__":
    prepare(Path(sys.argv[1]))
