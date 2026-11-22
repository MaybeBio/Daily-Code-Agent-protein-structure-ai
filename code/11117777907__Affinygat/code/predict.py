import os
import csv
import json
import torch
import numpy as np
from torch.utils.data import Dataset, DataLoader
from torch_geometric.data import Batch
from model_3 import AffinityGAT
from datetime import datetime
from tqdm import tqdm

# ============================= CONFIG =============================
# 存放待预测图数据的文件夹路径
GRAPH_DIR = "data/graphs_YZ_Wilforlide A"
STATS_FILE = "training_stats.json"

# 【GPU 调用核心】
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

BATCH_SIZE = 32
OUTPUT_DIR = "predict_YZ_Wilforlide A"
os.makedirs(OUTPUT_DIR, exist_ok=True)

print("="*60)
print("Protein-Ligand Affinity Prediction - Inference Mode")
print("="*60)
print(f"Target directory   : {GRAPH_DIR}")
print(f"Training stats     : {STATS_FILE}")
print(f"Device             : {DEVICE}")
if DEVICE.type == 'cuda':
    print(f"GPU Name           : {torch.cuda.get_device_name(0)}")
print(f"Batch size         : {BATCH_SIZE}")
print(f"Output directory   : {OUTPUT_DIR}")
print("-" * 60)

# 加载训练时的统计参数（必须使用训练集的均值和方差，以进行逆归一化和边特征缩放）
if not os.path.exists(STATS_FILE):
    raise FileNotFoundError(f"Missing stats file: {STATS_FILE}. Cannot perform correct scaling.")

with open(STATS_FILE) as f:
    stats = json.load(f)

aff_mean = torch.tensor(stats["aff_mean"], device=DEVICE)
aff_std  = torch.tensor(stats["aff_std"],  device=DEVICE)
edge_mu  = torch.tensor(stats["edge_mu"],  device=DEVICE)
edge_sig = torch.tensor(stats["edge_sigma"], device=DEVICE)

print(f"Loaded Affinity  mean/std : {stats['aff_mean']:.4f} / {stats['aff_std']:.4f}")
print(f"Loaded Edge dist mean/std : {stats['edge_mu']:.4f} / {stats['edge_sigma']:.4f}")
print("-" * 60)


class PredictDataset(Dataset):
    def __init__(self, graph_dir):
        self.graph_dir = graph_dir
        self.pdb_ids = []
        
        # 自动扫描目录下所有的 _combined.pt 文件
        for f in os.listdir(graph_dir):
            if f.endswith("_combined.pt"):
                pid = f[:-len("_combined.pt")]
                self.pdb_ids.append(pid)
                
        print(f"Found {len(self.pdb_ids)} valid complexes for prediction.")

    def __len__(self): 
        return len(self.pdb_ids)

    def __getitem__(self, i):
        pid = self.pdb_ids[i]
        path = os.path.join(self.graph_dir, f"{pid}_combined.pt")
        # 解除 PyTorch 2.6 的反序列化安全限制
        data = torch.load(path, map_location='cpu', weights_only=False)
        # 仅返回图数据和 ID，没有真实标签
        return data, pid


def collate_fn(b):
    # 只解包 data 和 pid
    d, p = zip(*b)
    return Batch.from_data_list(list(d)), p


def predict_ensemble(model_paths):
    print(f"Loading {len(model_paths)} ensemble models...")
    models = []
    for i, path in enumerate(model_paths):
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model not found: {path}")
        
        # 实例化模型并推入 GPU
        model = AffinityGAT(in_channels=34).to(DEVICE)
        model.load_state_dict(torch.load(path, map_location=DEVICE))
        model.eval()
        models.append(model)
        print(f"  [{i+1}/{len(model_paths)}] Loaded {path}")

    dataset = PredictDataset(GRAPH_DIR)
    
    if len(dataset) == 0:
        print("No complexes found to predict. Exiting.")
        return

    # 加入 pin_memory=True 加速数据到 GPU 的传输
    loader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=False, collate_fn=collate_fn, pin_memory=True)

    rows = []
    print("\nStarting prediction...")
    with torch.no_grad():
        for data, pids in tqdm(loader, desc="Predicting", unit="batch"):
            
            # 将图数据推入 GPU
            data = data.to(DEVICE)

            # 边特征的标准化处理（Z-score）
            if data.edge_attr is not None:
                dist = data.edge_attr[:, 0]
                data.edge_attr[:, 0] = (dist - edge_mu) / (edge_sig + 1e-12)

            # 集成预测，.view(-1) 处理模型输出确保形状正确
            preds = torch.stack([m(data).view(-1) for m in models]).mean(dim=0)
            
            # 使用训练集统计参数进行逆归一化，得到原始标度的 pKd
            pred_pkd = preds * aff_std + aff_mean

            # 将预测结果移回 CPU 并保存
            for pid, p in zip(pids, pred_pkd.cpu().numpy()):
                rows.append((pid, p))

    # 保存预测结果到 CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_file = os.path.join(OUTPUT_DIR, f"predict_results_{timestamp}.csv")
    
    with open(result_file, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pdb_id", "pred_pKd"])  # 仅输出 ID 和 预测值
        for pid, p in rows:
            w.writerow([pid, f"{p:.4f}"])

    print("="*60)
    print("PREDICTION COMPLETED")
    print("="*60)
    print(f"Total samples predicted : {len(rows)}")
    print(f"Results saved to        : {result_file}")
    print("-" * 60)


if __name__ == "__main__":
    # 请确保此处模型的文件名格式与 train.py 产出的格式一致
    paths = [f"affinity_gat_model_19_{i}.pt" for i in range(3)] 
    predict_ensemble(paths)