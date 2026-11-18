from Bio.PDB import PDBParser, PDBIO, Select

input_pdb = "../PGEL/examples/input_pdbs/5UDC.pdb"
output_pdb = "../PGEL/examples/input_pdbs/5UDC_HLF_clean.pdb"
keep_chains = {"H", "L", "F"}

parser = PDBParser(QUIET=True)
structure = parser.get_structure("5UDC", input_pdb)

class CleanSelect(Select):
    def accept_model(self, model):
        return model.id == 0

    def accept_chain(self, chain):
        return chain.id in keep_chains

    def accept_residue(self, residue):
        hetflag, resseq, icode = residue.id
        return hetflag == " " and residue.resname in {
            "ALA", "ARG", "ASN", "ASP", "CYS",
            "GLN", "GLU", "GLY", "HIS", "ILE",
            "LEU", "LYS", "MET", "PHE", "PRO",
            "SER", "THR", "TRP", "TYR", "VAL"
        }

    def accept_atom(self, atom):
        return atom.get_altloc() in (" ", "A")

# Renumber residues chain-by-chain
for model in structure:
    for chain in model:
        if chain.id not in keep_chains:
            continue

        new_number = 1
        for residue in list(chain):
            hetflag, old_number, insertion_code = residue.id

            if hetflag != " ":
                continue

            residue.id = (" ", new_number, " ")
            new_number += 1

io = PDBIO()
io.set_structure(structure)
io.save(output_pdb, CleanSelect())

print(f"Wrote {output_pdb}")

pdb = output_pdb
structure = PDBParser(QUIET=True).get_structure("x", pdb)

for chain in structure[0]:
    nums = [
        residue.id[1]
        for residue in chain
        if residue.id[0] == " "
    ]
    missing = sorted(set(range(min(nums), max(nums) + 1)) - set(nums))
    print(chain.id, min(nums), max(nums), "missing:", missing)