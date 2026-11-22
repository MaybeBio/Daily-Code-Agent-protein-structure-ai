import torch
import json
from model_attention import AffinityGAT

# 1. 基础配置
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
STATS_FILE = "training_stats.json"
MODEL_PATH = "affinity_gat_model_19_0.pt"
GRAPH_PATH = "data/graphs_attention/1H9Z_Toddalolactone_combined.pt"

# 2. 加载训练集的边距离统计信息 (与你的 test_3.py 保持一致，极其重要，否则模型识别不到正确的距离)
with open(STATS_FILE) as f:
    stats = json.load(f)
edge_mu = torch.tensor(stats["edge_mu"], device=DEVICE)
edge_sig = torch.tensor(stats["edge_sigma"], device=DEVICE)

# 3. 实例化模型并加载权重
print("Loading model weights...")
model = AffinityGAT(in_channels=34).to(DEVICE)
model.load_state_dict(torch.load(MODEL_PATH, map_location=DEVICE))
model.eval()

# 4. 加载目标图数据并进行与 test_3.py 相同的归一化处理
print("Loading specific complex graph...")
data = torch.load(GRAPH_PATH, map_location=DEVICE, weights_only=False)

if data.edge_attr is not None:
    dist = data.edge_attr[:, 0]
    data.edge_attr[:, 0] = (dist - edge_mu) / (edge_sig + 1e-12)

# 5. 前向传播：触发 return_attn 开关！
print("Extracting attention weights...")
with torch.no_grad():
    attn_edge_index, mean_attn_weights = model(data, return_attn=True)

# 6. 过滤交叉边并找出 Top 5
num_prot = data.num_prot_nodes # 必须在生成 graph.pt 时塞入这个属性
src = attn_edge_index[0]
dst = attn_edge_index[1]

# 找出从蛋白指向配体的边 (跨分子交叉边)
cross_mask = (src < num_prot) & (dst >= num_prot)
cross_edges = attn_edge_index[:, cross_mask]
cross_weights = mean_attn_weights[cross_mask]

top_k = 5
top_weights, top_indices = torch.topk(cross_weights, top_k)

print("\n" + "="*60)
print("TOP 5 KEY PHARMACOPHORIC INTERACTIONS FOUND BY AffinyGAT")
print("="*60)
for i in range(top_k):
    idx = top_indices[i]
    weight = top_weights[i].item()
    
    prot_node_id = cross_edges[0, idx].item()
    lig_node_id = cross_edges[1, idx].item()
    
    # 将图节点 ID 映射回 PDB 真实的残基和原子
    prot_res = data.prot_mapping[prot_node_id]          # e.g., ('TRP', 214)
    lig_atom = data.lig_mapping[lig_node_id - num_prot] # e.g., 'O3'
    
    print(f"Top {i+1} [Attention: {weight:.4f}]: Protein {prot_res[0]}{prot_res[1]} <---> Ligand {lig_atom}")
print("="*60)