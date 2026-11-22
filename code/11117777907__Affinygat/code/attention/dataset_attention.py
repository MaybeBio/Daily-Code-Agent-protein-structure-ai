import os
import torch
import numpy as np
from rdkit import Chem
from rdkit import RDLogger
from Bio.PDB import PDBParser, NeighborSearch, Selection
from torch_geometric.data import Data
from tqdm import tqdm

PDB_DIR = "D:/hsa_tianchan/hsa_pdb"
LIGAND_DIR = "D:/hsa_tianchan/ligand_sdf"
OUTPUT_GRAPH_DIR = "data/graphs_attention"
os.makedirs(OUTPUT_GRAPH_DIR, exist_ok=True)

# ============================= CONFIG =============================
FIXED_AMINO_ACIDS = ['ALA','ARG','ASN','ASP','CYS','GLN','GLU','GLY','HIS','ILE',
                     'LEU','LYS','MET','PHE','PRO','SER','THR','TRP','TYR','VAL']
FIXED_ATOM_TYPES = ['H','C','N','O','F','P','S','Cl','Br','I']

# Silence RDKit warnings
RDLogger.DisableLog('rdApp.*')

# ============================= LIGAND GRAPH =============================
def sdf_to_graph(sdf_file):
    try:
        mol = Chem.MolFromMolFile(sdf_file, removeHs=False, sanitize=False)
        if mol is None:
            print(f"Failed to read SDF: {sdf_file}")
            return None
        Chem.SanitizeMol(mol, catchErrors=True)
    except Exception as e:
        print(f"SDF parse error {sdf_file}: {e}")
        return None

    node_features = []
    coords = []
    lig_mapping = []  # === 新增：保存配体原子映射 ===
    
    conf = mol.GetConformer()
    for i, atom in enumerate(mol.GetAtoms()):
        sym = atom.GetSymbol() if atom.GetSymbol() in FIXED_ATOM_TYPES else 'C'
        onehot = [1 if sym == t else 0 for t in FIXED_ATOM_TYPES]
        charge = atom.GetFormalCharge()
        aromatic = int(atom.GetIsAromatic())
        node_features.append(onehot + [charge, aromatic])
        
        pos = conf.GetAtomPosition(i)
        coords.append([pos.x, pos.y, pos.z])
        
        # 记录原子名称，例如 "O1", "C2"
        lig_mapping.append(f"{atom.GetSymbol()}{i+1}")

    x = torch.tensor(node_features, dtype=torch.float)
    pos = torch.tensor(coords, dtype=torch.float)

    # Ligand bonds
    edge_index, edge_attr = [], []
    for bond in mol.GetBonds():
        u, v = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        edge_index.extend([[u, v], [v, u]])
        edge_attr.extend([[0.0, 2.0, 0.0]] * 2)

    edge_index = torch.tensor(edge_index, dtype=torch.long).t().contiguous() if edge_index else torch.empty((2, 0), dtype=torch.long)
    edge_attr = torch.tensor(edge_attr, dtype=torch.float) if edge_attr else torch.empty((0, 3), dtype=torch.float)

    # === 新增：将 lig_mapping 传入 Data ===
    return Data(x=x, pos=pos, edge_index=edge_index, edge_attr=edge_attr, mol=mol, lig_mapping=lig_mapping)

# ============================= PROTEIN GRAPH =============================
def pdb_to_graph(pdb_file, ligand_coords=None):

    parser = PDBParser(QUIET=True)

    try:
        import gzip
        with open(pdb_file, "rb") as f:
            magic = f.read(2)
        if magic == b'\x1f\x8b':
            print(f"Detected gzip PDB: {pdb_file}")
            with gzip.open(pdb_file, "rt") as handle:
                structure = parser.get_structure('prot', handle)
        else:
            with open(pdb_file, "r", encoding="utf-8", errors="ignore") as handle:
                structure = parser.get_structure('prot', handle)
    except Exception as e:
        print(f"PDB parse failed: {pdb_file} - {e}")
        return None

    residues = []
    coords = []
    residue_to_idx = {}

    for model in structure:
        for chain in model:
            for residue in chain:
                if residue.get_id()[0] != ' ':   # 跳过 HETATM
                    continue
                if 'CA' not in residue:
                    continue
                ca = residue['CA']
                coord = ca.coord
                if ligand_coords is not None:
                    dists = np.linalg.norm(ligand_coords - coord, axis=1)
                    if dists.min() > 12.0:       # 稍微放宽
                        continue
                residues.append(residue)
                coords.append(coord)
                residue_to_idx[residue] = len(residues) - 1

    if not residues:
        print(f"No valid residues in {pdb_file}")
        return None

    # Node features
    node_features = []
    prot_mapping = []  # === 新增：保存蛋白残基映射 ===
    
    for res in residues:
        aa = res.resname.strip()
        onehot = [1 if aa == a else 0 for a in FIXED_AMINO_ACIDS]
        charge = 1 if aa in ['ARG', 'LYS', 'HIS'] else (-1 if aa in ['ASP', 'GLU'] else 0)
        hydrophobic = 1 if aa in ['ALA', 'VAL', 'LEU', 'ILE', 'MET', 'PHE', 'TRP', 'PRO'] else 0
        node_features.append(onehot + [charge, hydrophobic])
        
        # 记录氨基酸名称和序号，例如 ('TRP', 214)
        res_id = res.get_id()[1]
        prot_mapping.append((aa, res_id))

    x = torch.tensor(node_features, dtype=torch.float)
    pos = torch.tensor(coords, dtype=torch.float)

    # Edges
    edge_index, edge_attr = [], []
    atom_list = list(Selection.unfold_entities(residues, 'A'))
    ns = NeighborSearch(atom_list)

    # Sequential
    for i in range(len(residues) - 1):
        d = np.linalg.norm(coords[i] - coords[i + 1])
        edge_index.extend([[i, i + 1], [i + 1, i]])
        edge_attr.extend([[d, 1.0, 0.0]] * 2)

    # H-bond & Disulfide
    for atom1, atom2 in ns.search_all(3.5, 'R'):
        res1 = atom1.get_parent()
        res2 = atom2.get_parent()
        if res1 not in residue_to_idx or res2 not in residue_to_idx:
            continue
        i1 = residue_to_idx[res1]
        i2 = residue_to_idx[res2]
        d = np.linalg.norm(atom1.coord - atom2.coord)

        if atom1.element == 'S' and atom2.element == 'S' and d < 2.5:
            edge_index.extend([[i1, i2], [i2, i1]])
            edge_attr.extend([[d, 1.0, 7.0]] * 2)   # disulfide
        elif (atom1.element in ['N', 'O'] and atom2.element in ['N', 'O', 'F']):
            edge_index.extend([[i1, i2], [i2, i1]])
            edge_attr.extend([[d, 1.0, 1.0]] * 2)   # hbond

    edge_index = torch.tensor(edge_index, dtype=torch.long).t().contiguous() if edge_index else torch.empty((2, 0), dtype=torch.long)
    edge_attr = torch.tensor(edge_attr, dtype=torch.float) if edge_attr else torch.empty((0, 3), dtype=torch.float)

    # === 新增：将 prot_mapping 传入 Data ===
    return Data(x=x, pos=pos, edge_index=edge_index, edge_attr=edge_attr, residues=residues, prot_mapping=prot_mapping)

# ============================= COMBINE GRAPH =============================
def combine_graph(prot_graph, lig_graph, cross_cutoffs=[4.0, 6.0, 10.0]):
    if prot_graph is None or lig_graph is None:
        return None

    # Node feature concatenation (protein 22 + ligand 12 = 34)
    px = torch.cat([prot_graph.x, torch.zeros((prot_graph.x.size(0), 12), dtype=torch.float)], dim=1)
    lx = torch.cat([torch.zeros((lig_graph.x.size(0), 22), dtype=torch.float), lig_graph.x], dim=1)
    x = torch.cat([px, lx], dim=0)

    edge_index_list = []
    edge_attr_list = []
    offset = prot_graph.x.size(0)

    # Protein intra edges
    if prot_graph.edge_index.size(1) > 0:
        ei, ea = prot_graph.edge_index, prot_graph.edge_attr
        for k in range(ei.size(1)):
            u, v = ei[0, k].item(), ei[1, k].item()
            d, etype, itype = ea[k].tolist()
            edge_index_list.extend([[u, v], [v, u]])
            edge_attr_list.extend([[d, etype, itype]] * 2)

    # Ligand intra edges
    if lig_graph.edge_index.size(1) > 0:
        ei = lig_graph.edge_index
        for k in range(ei.size(1)):
            u = ei[0, k].item() + offset
            v = ei[1, k].item() + offset
            edge_index_list.extend([[u, v], [v, u]])
            edge_attr_list.extend([[0.0, 2.0, 0.0]] * 2)

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
            ca_atom = res['CA'] if 'CA' in res else next(iter(res.get_atoms()))

            itype = 6  # other
            if dist < 3.5 and ((ca_atom.element in ['N','O'] and lig_atom.GetSymbol() in ['N','O','F']) or
                               (lig_atom.GetSymbol() in ['N','O'] and ca_atom.element in ['N','O'])):
                itype = 1
            elif dist < 5.5 and ((ca_atom.element == 'N' and lig_atom.GetSymbol() == 'O') or
                                 (ca_atom.element == 'O' and lig_atom.GetSymbol() == 'N')):
                itype = 2
            elif any(a.GetIsAromatic() for a in lig_mol.GetAtoms()) and res.resname in ['PHE','TYR','TRP','HIS']:
                itype = 3
            elif lig_atom.GetSymbol() in ['Cl','Br','I'] and ca_atom.element in ['O','N','S'] and dist < 4.0:
                itype = 4
            elif ca_atom.element in ['ZN','MG','FE','CU'] or lig_atom.GetSymbol() in ['ZN','MG','FE','CU']:
                itype = 5

            u, v = i, offset + j
            edge_index_list.extend([[u, v], [v, u]])
            edge_attr_list.extend([[dist, scale_type, float(itype)]] * 2)

    edge_index = torch.tensor(edge_index_list, dtype=torch.long).t().contiguous() if edge_index_list else torch.empty((2, 0), dtype=torch.long)
    edge_attr = torch.tensor(edge_attr_list, dtype=torch.float) if edge_attr_list else torch.empty((0, 3), dtype=torch.float)

    # === 核心修改：将所有映射字典挂载到最终合并的 Data 对象上 ===
    combined_data = Data(x=x, edge_index=edge_index, edge_attr=edge_attr)
    combined_data.num_prot_nodes = prot_graph.x.size(0)            # 极其关键！区分蛋白和配体
    combined_data.prot_mapping = prot_graph.prot_mapping           # 挂载氨基酸名称映射
    combined_data.lig_mapping = lig_graph.lig_mapping              # 挂载配体原子名称映射
    
    return combined_data

if __name__ == "__main__":

    pdb_files = [f for f in os.listdir(PDB_DIR) if f.endswith(".pdb")]
    ligand_files = [f for f in os.listdir(LIGAND_DIR) if f.endswith(".sdf")]

    print("="*60)
    print(f"Protein number : {len(pdb_files)}")
    print(f"Ligand number  : {len(ligand_files)}")
    print(f"Total graphs   : {len(pdb_files)*len(ligand_files)}")
    print("="*60)

    processed = 0

    for pdb_name in tqdm(pdb_files, desc="Processing proteins"):
        pdb_id = os.path.splitext(pdb_name)[0]
        pdb_path = os.path.join(PDB_DIR, pdb_name)

        for ligand_name in ligand_files:
            ligand_id = os.path.splitext(ligand_name)[0]
            sdf_path = os.path.join(LIGAND_DIR, ligand_name)
            save_name = f"{pdb_id}_{ligand_id}"

            try:
                lig_graph = sdf_to_graph(sdf_path)
                if lig_graph is None: continue

                prot_graph = pdb_to_graph(pdb_path, ligand_coords=lig_graph.pos.numpy())
                if prot_graph is None: continue

                combined = combine_graph(prot_graph, lig_graph)
                if combined is None: continue

                torch.save(prot_graph, os.path.join(OUTPUT_GRAPH_DIR, f"{save_name}_protein.pt"))
                torch.save(lig_graph, os.path.join(OUTPUT_GRAPH_DIR, f"{save_name}_ligand.pt"))
                
                # === 保存携带完整映射信息的 combined.pt ===
                torch.save(combined, os.path.join(OUTPUT_GRAPH_DIR, f"{save_name}_combined.pt"))

                processed += 1

            except Exception as e:
                print(f"Error {save_name}: {e}")
                with open(os.path.join(OUTPUT_GRAPH_DIR, "error.log"), "a") as f:
                    f.write(f"{save_name}: {e}\n")

    print("="*60)
    print(f"Finished! Generated {processed} complexes")
    print(f"Saved to {OUTPUT_GRAPH_DIR}")
    print("="*60)