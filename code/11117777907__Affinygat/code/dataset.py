import os
import torch
import numpy as np
from rdkit import Chem
from rdkit import RDLogger
from Bio.PDB import PDBParser, NeighborSearch, Selection
from torch_geometric.data import Data
from tqdm import tqdm

# ============================= PATH SETTINGS =============================
INPUT_DATA_ROOT = "D:/pdbbind/CASF-2016/coreset"
OUTPUT_GRAPH_DIR = "data/graphs_test_2016_627"
os.makedirs(OUTPUT_GRAPH_DIR, exist_ok=True)

# ============================= CONFIG =============================
FIXED_AMINO_ACIDS = ['ALA','ARG','ASN','ASP','CYS','GLN','GLU','GLY','HIS','ILE',
                     'LEU','LYS','MET','PHE','PRO','SER','THR','TRP','TYR','VAL']
FIXED_ATOM_TYPES = ['H','C','N','O','F','P','S','Cl','Br','I']

# Interaction type encoding
INTERACTION_TYPES = {
    'hydrophobic': 0,
    'hbond':       1,
    'saltbridge':  2,
    'pistack':     3,
    'halogen':     4,
    'metal':       5,
    'other':       6
}

# Silence RDKit warnings
RDLogger.DisableLog('rdApp.*')

# ============================= LIGAND GRAPH =============================
def sdf_to_graph(sdf_file):
    try:
        # 关闭 sanitize，跳过价态检查
        mol = Chem.MolFromMolFile(sdf_file, removeHs=False, sanitize=False)
        if mol is None:
            return None
        Chem.SanitizeMol(mol, catchErrors=True)  # 温和处理
    except Exception as e:
        print(f"SDF parse failed: {sdf_file}")
        return None

    num_atoms = mol.GetNumAtoms()
    node_features = []
    coords = []
    conf = mol.GetConformer()
    for i, atom in enumerate(mol.GetAtoms()):
        sym = atom.GetSymbol() if atom.GetSymbol() in FIXED_ATOM_TYPES else 'C'
        onehot = [1 if sym == t else 0 for t in FIXED_ATOM_TYPES]
        charge = atom.GetFormalCharge()
        aromatic = int(atom.GetIsAromatic())
        node_features.append(onehot + [charge, aromatic])
        pos = conf.GetAtomPosition(i)
        coords.append([pos.x, pos.y, pos.z])

    x = torch.tensor(node_features, dtype=torch.float)
    pos = torch.tensor(coords, dtype=torch.float)  # 直接用 np.array → tensor

    edge_index, edge_attr = [], []
    for bond in mol.GetBonds():
        u, v = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        bt = float(bond.GetBondTypeAsDouble())
        edge_index.extend([[u,v],[v,u]])
        edge_attr.extend([[0.0, 2.0, 0.0]]*2)  # distance filled later
    edge_index = torch.tensor(edge_index, dtype=torch.long).t().contiguous() if edge_index else torch.empty((2,0), dtype=torch.long)
    edge_attr = torch.tensor(edge_attr, dtype=torch.float) if edge_attr else torch.empty((0,3), dtype=torch.float)

    return Data(x=x, pos=pos, edge_index=edge_index, edge_attr=edge_attr, mol=mol)

# ============================= PROTEIN GRAPH =============================
def pdb_to_graph(pdb_file, ligand_coords=None, ligand_mol=None):
    parser = PDBParser(QUIET=True)
    try:
        structure = parser.get_structure('prot', pdb_file)
    except:
        return None

    residues = []
    coords = []
    residue_to_idx = {}  # 用于快速查找索引

    for model in structure:
        for chain in model:
            for residue in chain:
                if residue.get_id()[0] != ' ':  # skip HETATM
                    continue
                if 'CA' not in residue:
                    continue
                ca = residue['CA']
                coord = ca.coord
                if ligand_coords is not None:
                    dists = np.linalg.norm(ligand_coords - coord, axis=1)
                    if dists.min() > 10.0:
                        continue
                residues.append(residue)
                coords.append(coord)
                residue_to_idx[residue] = len(residues) - 1

    if not residues:
        return None

    # Node features
    node_features = []
    for res in residues:
        aa = res.resname
        onehot = [1 if aa == a else 0 for a in FIXED_AMINO_ACIDS]
        charge = 1 if aa in ['ARG','LYS','HIS'] else (-1 if aa in ['ASP','GLU'] else 0)
        hydrophobic = 1 if aa in ['ALA','VAL','LEU','ILE','MET','PHE','TRP','PRO'] else 0
        node_features.append(onehot + [charge, hydrophobic])
    x = torch.tensor(node_features, dtype=torch.float)
    pos = torch.tensor(coords, dtype=torch.float)

    # Edges
    edge_index, edge_attr = [], []
    atom_list = list(Selection.unfold_entities(residues, 'A'))
    ns = NeighborSearch(atom_list)

    # Sequential edges
    for i in range(len(residues)-1):
        d = np.linalg.norm(coords[i] - coords[i+1])
        edge_index.extend([[i,i+1],[i+1,i]])
        edge_attr.extend([[d, 1.0, 0.0]]*2)

    # H-bond and disulfide
    for atom1, atom2 in ns.search_all(3.5, 'R'):
        res1 = atom1.get_parent()
        res2 = atom2.get_parent()
        if res1 not in residue_to_idx or res2 not in residue_to_idx:
            continue
        i1, i2 = residue_to_idx[res1], residue_to_idx[res2]
        d = np.linalg.norm(atom1.coord - atom2.coord)

        if atom1.element == 'S' and atom2.element == 'S' and d < 2.5:
            edge_index.extend([[i1,i2],[i2,i1]])
            edge_attr.extend([[d, 1.0, 7.0]]*2)  # disulfide
        elif (atom1.element in ['N','O'] and atom2.element in ['N','O','F']):
            edge_index.extend([[i1,i2],[i2,i1]])
            edge_attr.extend([[d, 1.0, 1.0]]*2)  # hbond

    edge_index = torch.tensor(edge_index, dtype=torch.long).t().contiguous() if edge_index else torch.empty((2,0), dtype=torch.long)
    edge_attr = torch.tensor(edge_attr, dtype=torch.float) if edge_attr else torch.empty((0,3), dtype=torch.float)

    return Data(x=x, pos=pos, edge_index=edge_index, edge_attr=edge_attr, residues=residues)

# ============================= COMBINE GRAPH =============================
def combine_graph(prot_graph, lig_graph, cross_cutoffs=[4.0, 6.0, 10.0]):
    if prot_graph is None or lig_graph is None:
        return None

    px = torch.cat([prot_graph.x, torch.zeros((prot_graph.x.size(0), 12), dtype=torch.float)], dim=1)
    lx = torch.cat([torch.zeros((lig_graph.x.size(0), 22), dtype=torch.float), lig_graph.x], dim=1)
    x = torch.cat([px, lx], dim=0)

    edge_index_list = []
    edge_attr_list = []
    offset = prot_graph.x.size(0)

    # Protein intra
    if prot_graph.edge_index.size(1) > 0:
        ei, ea = prot_graph.edge_index, prot_graph.edge_attr
        for i in range(ei.size(1)):
            u, v = ei[0,i].item(), ei[1,i].item()
            d, etype, itype = ea[i].tolist()
            edge_index_list.extend([[u,v],[v,u]])
            edge_attr_list.extend([[d, etype, itype]]*2)

    # Ligand intra
    if lig_graph.edge_index.size(1) > 0:
        ei, ea = lig_graph.edge_index, lig_graph.edge_attr
        for i in range(ei.size(1)):
            u, v = ei[0,i].item() + offset, ei[1,i].item() + offset
            edge_index_list.extend([[u,v],[v,u]])
            edge_attr_list.extend([[0.0, 2.0, 0.0]]*2)  # distance filled later

    # Cross edges
    prot_pos = prot_graph.pos.numpy()
    lig_pos = lig_graph.pos.numpy()
    lig_mol = lig_graph.mol

    for i, pcoord in enumerate(prot_pos):
        res = prot_graph.residues[i]
        for j, lcoord in enumerate(lig_pos):
            dist = np.linalg.norm(pcoord - lcoord)
            if dist > max(cross_cutoffs):
                continue

            scale_type = 4.0 if dist <= 4.0 else (5.0 if dist <= 6.0 else 6.0)

            lig_atom = lig_mol.GetAtomWithIdx(j)
            ca_atom = res['CA'] if 'CA' in res else list(res.get_atoms())[0]

            itype = 6
            if (ca_atom.element in ['N','O'] and lig_atom.GetSymbol() in ['O','N','F']) or \
               (lig_atom.GetSymbol() in ['N','O'] and ca_atom.element in ['O','N']):
                if dist < 3.5:
                    itype = 1  # hbond
            elif dist < 5.5 and ((ca_atom.element == 'N' and lig_atom.GetSymbol() == 'O') or
                                (ca_atom.element == 'O' and lig_atom.GetSymbol() == 'N')):
                itype = 2  # saltbridge
            elif any(atom.GetIsAromatic() for atom in lig_mol.GetAtoms()) and res.resname in ['PHE','TYR','TRP','HIS']:
                itype = 3  # pistack
            elif lig_atom.GetSymbol() in ['Cl','Br','I'] and ca_atom.element in ['O','N','S'] and dist < 4.0:
                itype = 4  # halogen
            elif ca_atom.element in ['ZN','MG','FE','CU'] or lig_atom.GetSymbol() in ['ZN','MG','FE','CU']:
                itype = 5  # metal

            u, v = i, offset + j
            edge_index_list.extend([[u,v],[v,u]])
            edge_attr_list.extend([[dist, scale_type, float(itype)]]*2)

    edge_index = torch.tensor(edge_index_list, dtype=torch.long).t().contiguous() if edge_index_list else torch.empty((2,0), dtype=torch.long)
    edge_attr = torch.tensor(edge_attr_list, dtype=torch.float) if edge_attr_list else torch.empty((0,3), dtype=torch.float)

    return Data(x=x, edge_index=edge_index, edge_attr=edge_attr)

# ============================= MAIN =============================
if __name__ == "__main__":
    pdb_ids = [d for d in os.listdir(INPUT_DATA_ROOT) if os.path.isdir(os.path.join(INPUT_DATA_ROOT, d))]
    print(f"Found {len(pdb_ids)} complexes")

    for pdb_id in tqdm(pdb_ids, desc="Processing"):
        folder = os.path.join(INPUT_DATA_ROOT, pdb_id)
        pdb_file = os.path.join(folder, f"{pdb_id}_protein.pdb")
        sdf_file = os.path.join(folder, f"{pdb_id}_ligand.sdf")

        if not (os.path.exists(pdb_file) and os.path.exists(sdf_file)):
            continue

        try:
            lig_graph = sdf_to_graph(sdf_file)
            if lig_graph is None:
                continue

            prot_graph = pdb_to_graph(pdb_file, ligand_coords=lig_graph.pos.numpy(), ligand_mol=lig_graph.mol)
            if prot_graph is None:
                continue

            combined = combine_graph(prot_graph, lig_graph)
            if combined is None:
                continue

            torch.save(prot_graph, os.path.join(OUTPUT_GRAPH_DIR, f"{pdb_id}_protein.pt"))
            torch.save(lig_graph,  os.path.join(OUTPUT_GRAPH_DIR, f"{pdb_id}_ligand.pt"))
            torch.save(combined,   os.path.join(OUTPUT_GRAPH_DIR, f"{pdb_id}_combined.pt"))

        except Exception as e:
            with open(os.path.join(OUTPUT_GRAPH_DIR, "error.log"), "a") as f:
                f.write(f"{pdb_id}: {e}\n")

    print(f"Done! Graphs saved to {OUTPUT_GRAPH_DIR}")