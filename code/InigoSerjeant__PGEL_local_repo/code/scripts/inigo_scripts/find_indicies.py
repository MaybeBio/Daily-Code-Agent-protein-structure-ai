from Bio.PDB import PDBParser
from Bio.SeqUtils import seq1

pdb_file = "../PGEL/examples/input_pdbs/5UDC_HLF_clean.pdb"
cdr_sequence = "VSETYLPHYFDN"

parser = PDBParser(QUIET=True)
structure = parser.get_structure("antibody", pdb_file)

for chain in structure[0]:

    residues = [
        r for r in chain
        if r.id[0] == " " and r.has_id("CA")
    ]

    sequence = "".join(
        seq1(r.resname, custom_map={"UNK": "X"})
        for r in residues
    )

    position = sequence.find(cdr_sequence)

    if position != -1:

        matched_residues = residues[
            position:position + len(cdr_sequence)
        ]

        print(f"\nChain: {chain.id}")
        print(f"CDR-H3: {cdr_sequence}")
        print(f"Sequence position: {position + 1}-{position + len(cdr_sequence)}")
        print("PDB residue IDs:")

        for residue in matched_residues:
            print(residue.id)

        print(
            f"Contiguous PDB range: "
            f"{matched_residues[0].id[1]}-{matched_residues[-1].id[1]}"
        )