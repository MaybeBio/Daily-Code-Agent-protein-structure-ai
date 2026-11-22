import os
import torch
import json
import numpy as np
from rdkit import Chem
from Bio.PDB import PDBParser, NeighborSearch, Selection
from torch_geometric.data import Data

# 导入你的模型结构
from model_attention import AffinityGAT

# ================= 1. 基础配置 (请检查路径) =================
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
TARGET_PDB_ID = "3f17"

# 你的模型和统计文件路径
STATS_FILE = "training_stats.json"           
MODEL_PATH = "affinity_gat_model_19_1.pt"    

# 原始 PDB 和 SDF 的路径 (请根据你电脑的实际位置修改)
INPUT_PDB_FILE = f"D:/pdbbind/CASF-2013/coreset/3f17/3f17_protein.pdb"
INPUT_SDF_FILE = f"D:/pdbbind/v2019/3f17/3f17_ligand.sdf" # 或对应的sdf路径

OUTPUT_PDB_FILE = f"{TARGET_PDB_ID}_attention_weighted.pdb"

# ================= 2. 构图所需常数与函数 (带 Mapping) =================
FIXED_AMINO_ACIDS = ['ALA','ARG','ASN','ASP','CYS','GLN','GLU','GLY','HIS','ILE',
                     'LEU','LYS','MET','PHE','PRO','SER','THR','TRP','TYR','VAL']
FIXED_ATOM_TYPES = ['H','C','N','O','F','P','S','Cl','Br','I']

def sdf_to_graph(sdf_file):
    mol = Chem.MolFromMolFile(sdf_file, removeHs=False, sanitize=False)
    Chem.SanitizeMol(mol, catchErrors=True)
    node_features, coords, lig_mapping = [], [], []
    conf = mol.GetConformer()
    for i, atom in enumerate(mol.GetAtoms()):
        sym = atom.GetSymbol() if atom.GetSymbol() in FIXED_ATOM_TYPES else 'C'
        onehot = [1 if sym == t else 0 for t in FIXED_ATOM_TYPES]
        node_features.append(onehot + [atom.GetFormalCharge(), int(atom.GetIsAromatic())])
        pos = conf.GetAtomPosition(i)
        coords.append([pos.x, pos.y, pos.z])
        lig_mapping.append(f"{atom.GetSymbol()}{i+1}")
    
    x = torch.tensor(node_features, dtype=torch.float)
    pos = torch.tensor(coords, dtype=torch.float)
    
    edge_index, edge_attr = [], []
    for bond in mol.GetBonds():
        u, v = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        edge_index.extend([[u, v], [v, u]])
        edge_attr.extend([[0.0, 2.0, 0.0]] * 2)
    edge_index = torch.tensor(edge_index, dtype=torch.long).t().contiguous() if edge_index else torch.empty((2, 0), dtype=torch.long)
    edge_attr = torch.tensor(edge_attr, dtype=torch.float) if edge_attr else torch.empty((0, 3), dtype=torch.float)
    
    return Data(x=x, pos=pos, edge_index=edge_index, edge_attr=edge_attr, mol=mol, lig_mapping=lig_mapping)

def pdb_to_graph(pdb_file, ligand_coords):
    parser = PDBParser(QUIET=True)
    structure = parser.get_structure('prot', pdb_file)
    residues, coords, prot_mapping, residue_to_idx = [], [], [], {}
    
    for model in structure:
        for chain in model:
            for residue in chain:
                if residue.get_id()[0] != ' ': continue
                if 'CA' not in residue: continue
                coord = residue['CA'].coord
                # 距离过滤 (与原本处理数据逻辑一致)
                if np.linalg.norm(ligand_coords - coord, axis=1).min() > 12.0: continue
                
                residues.append(residue)
                coords.append(coord)
                residue_to_idx[residue] = len(residues) - 1
                
                aa = residue.resname.strip()
                res_id = residue.get_id()[1]
                prot_mapping.append((aa, res_id))

    node_features = []
    for aa, _ in prot_mapping:
        onehot = [1 if aa == a else 0 for a in FIXED_AMINO_ACIDS]
        charge = 1 if aa in ['ARG','LYS','HIS'] else (-1 if aa in ['ASP','GLU'] else 0)
        hydro = 1 if aa in ['ALA','VAL','LEU','ILE','MET','PHE','TRP','PRO'] else 0
        node_features.append(onehot + [charge, hydro])
        
    x = torch.tensor(node_features, dtype=torch.float)
    pos = torch.tensor(coords, dtype=torch.float)
    
    edge_index, edge_attr = [], []
    ns = NeighborSearch(list(Selection.unfold_entities(residues, 'A')))
    for i in range(len(residues) - 1):
        edge_index.extend([[i, i + 1], [i + 1, i]])
        edge_attr.extend([[np.linalg.norm(coords[i] - coords[i + 1]), 1.0, 0.0]] * 2)
    for a1, a2 in ns.search_all(3.5, 'R'):
        r1, r2 = a1.get_parent(), a2.get_parent()
        if r1 in residue_to_idx and r2 in residue_to_idx:
            d = np.linalg.norm(a1.coord - a2.coord)
            if a1.element == 'S' and a2.element == 'S' and d < 2.5:
                edge_index.extend([[residue_to_idx[r1], residue_to_idx[r2]], [residue_to_idx[r2], residue_to_idx[r1]]])
                edge_attr.extend([[d, 1.0, 7.0]] * 2)
            elif a1.element in ['N','O'] and a2.element in ['N','O','F']:
                edge_index.extend([[residue_to_idx[r1], residue_to_idx[r2]], [residue_to_idx[r2], residue_to_idx[r1]]])
                edge_attr.extend([[d, 1.0, 1.0]] * 2)
                
    edge_index = torch.tensor(edge_index, dtype=torch.long).t().contiguous() if edge_index else torch.empty((2, 0), dtype=torch.long)
    edge_attr = torch.tensor(edge_attr, dtype=torch.float) if edge_attr else torch.empty((0, 3), dtype=torch.float)
    return Data(x=x, pos=pos, edge_index=edge_index, edge_attr=edge_attr, prot_mapping=prot_mapping, residues=residues)

def combine_graph(prot_graph, lig_graph):
    px = torch.cat([prot_graph.x, torch.zeros((prot_graph.x.size(0), 12), dtype=torch.float)], dim=1)
    lx = torch.cat([torch.zeros((lig_graph.x.size(0), 22), dtype=torch.float), lig_graph.x], dim=1)
    x = torch.cat([px, lx], dim=0)
    
    edge_index_list, edge_attr_list = [], []
    offset = prot_graph.x.size(0)
    
    if prot_graph.edge_index.size(1) > 0:
        for k in range(prot_graph.edge_index.size(1)):
            edge_index_list.append([prot_graph.edge_index[0, k].item(), prot_graph.edge_index[1, k].item()])
            edge_attr_list.append(prot_graph.edge_attr[k].tolist())
    if lig_graph.edge_index.size(1) > 0:
        for k in range(lig_graph.edge_index.size(1)):
            edge_index_list.append([lig_graph.edge_index[0, k].item() + offset, lig_graph.edge_index[1, k].item() + offset])
            edge_attr_list.append([0.0, 2.0, 0.0])
            
    for i, pcoord in enumerate(prot_graph.pos.numpy()):
        for j, lcoord in enumerate(lig_graph.pos.numpy()):
            dist = np.linalg.norm(pcoord - lcoord)
            if dist <= 10.0:
                u, v = i, offset + j
                scale = 4.0 if dist <= 4.0 else (5.0 if dist <= 6.0 else 6.0)
                edge_index_list.extend([[u, v], [v, u]])
                edge_attr_list.extend([[dist, scale, 6.0]] * 2) # Simplified itype for space
                
    combined_data = Data(
        x=x, 
        edge_index=torch.tensor(edge_index_list, dtype=torch.long).t().contiguous(), 
        edge_attr=torch.tensor(edge_attr_list, dtype=torch.float)
    )
    combined_data.num_prot_nodes = prot_graph.x.size(0)
    combined_data.prot_mapping = prot_graph.prot_mapping
    return combined_data

def inject_weights_to_pdb(input_pdb, output_pdb, weights_dict):
    with open(input_pdb, 'r', encoding='utf-8', errors='ignore') as f_in, open(output_pdb, 'w', encoding='utf-8') as f_out:
        for line in f_in:
            if line.startswith("ATOM") or line.startswith("HETATM"):
                res_seq = line[22:26].strip()
                weight = weights_dict.get(res_seq, 0.0)
                f_out.write(line[:60] + f"{weight:>6.2f}" + line[66:])
            else:
                f_out.write(line)
    print(f"✅ 成功生成带权重的 PDB 文件: {output_pdb}")

# ================= 3. 执行端到端提取 =================
# ================= 3. 执行端到端提取 (优化版) =================
print("1. 动态生成包含 mapping 的图数据...")
lig_g = sdf_to_graph(INPUT_SDF_FILE)
prot_g = pdb_to_graph(INPUT_PDB_FILE, lig_g.pos.numpy())
data = combine_graph(prot_g, lig_g).to(DEVICE)

print("2. 加载模型及统计信息...")
with open(STATS_FILE) as f:
    stats = json.load(f)
edge_mu, edge_sig = torch.tensor(stats["edge_mu"], device=DEVICE), torch.tensor(stats["edge_sigma"], device=DEVICE)

model = AffinityGAT(in_channels=34).to(DEVICE)
model.load_state_dict(torch.load(MODEL_PATH, map_location=DEVICE))
model.eval()

# 边归一化
data.edge_attr[:, 0] = (data.edge_attr[:, 0] - edge_mu) / (edge_sig + 1e-12)

print("3. 前向传播提取注意力...")
with torch.no_grad():
    attn_edge_index, mean_attn_weights = model(data, return_attn=True)

print("4. 聚合、优化归一化权重并注入 PDB...")
cross_mask = (attn_edge_index[0] < data.num_prot_nodes) & (attn_edge_index[1] >= data.num_prot_nodes)
cross_edges = attn_edge_index[:, cross_mask]
cross_weights = mean_attn_weights[cross_mask]

node_attn_sum = torch.zeros(data.num_prot_nodes, device=DEVICE)
node_attn_sum.scatter_add_(0, cross_edges[0], cross_weights)

# 优化策略：使用非线性平滑（如平方根或对数拉伸），让中低权重也能显形，而不是被极值拉开差距
node_attn_sum = torch.sqrt(node_attn_sum + 1e-8)

min_w, max_w = node_attn_sum.min(), node_attn_sum.max()
node_attn_norm = (node_attn_sum - min_w) / (max_w - min_w) if max_w > min_w else node_attn_sum

gat_weights_dict = {}
for i in range(data.num_prot_nodes):
    w = node_attn_norm[i].item()
    res_seq = str(data.prot_mapping[i][1])
    
    # 【关键改动】不再使用 w > 0.01 的粗暴过滤，只要在 10Å 口袋内就赋予其实际权重
    # 如果权重极小（例如 < 0.001），可以给一个微小的底线或者直接赋真实值
    gat_weights_dict[res_seq] = w
    
    if w > 0.4:
        print(f"  高亮关键残基 {data.prot_mapping[i][0]} {res_seq}: 权重 {w:.4f}")

inject_weights_to_pdb(INPUT_PDB_FILE, OUTPUT_PDB_FILE, gat_weights_dict)