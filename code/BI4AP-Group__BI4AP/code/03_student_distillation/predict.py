import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import argparse
import logging
import numpy as np
import pandas as pd
import torch
import time
from torch import nn
from torch.utils.data import Dataset, DataLoader
from transformers import AutoTokenizer, AutoModel
import warnings
from sklearn.exceptions import InconsistentVersionWarning
from tqdm import tqdm
from rdkit import Chem
from sklearn.metrics import r2_score
from scipy.stats import spearmanr

warnings.filterwarnings("ignore", category=InconsistentVersionWarning)

def setup_logger():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# ========= 模型定义 (必须与训练代码完全一致) ========= #
class ResidualBlock(nn.Module):
    def __init__(self, dim, dropout_rate=0.2):
        super().__init__()
        self.block = nn.Sequential(nn.Linear(dim, dim), nn.GELU(), nn.Dropout(dropout_rate), nn.Linear(dim, dim))
        self.norm = nn.LayerNorm(dim)
        self.dropout = nn.Dropout(dropout_rate)
    def forward(self, x): return self.norm(x + self.dropout(self.block(x)))

class EnhancedStudentModel(nn.Module):
    def __init__(self, in_dim, lig_dim, pkt_dim, attn_layers, attn_dim, hidden_dims=[512, 512, 256, 128], dropout_rate=0.4):
        super().__init__()
        self.lig_dim, self.pkt_dim, self.attn_layers, self.attn_dim = lig_dim, pkt_dim, attn_layers, attn_dim
        layers, prev_dim = [], in_dim
        layers.extend([nn.Linear(prev_dim, hidden_dims[0]), nn.GELU(), nn.Dropout(dropout_rate), nn.LayerNorm(hidden_dims[0])])
        prev_dim = hidden_dims[0]
        for h_dim in hidden_dims[1:]:
            layers.append(ResidualBlock(prev_dim, dropout_rate))
            if h_dim != prev_dim:
                layers.extend([nn.Linear(prev_dim, h_dim), nn.GELU(), nn.Dropout(dropout_rate), nn.LayerNorm(h_dim)])
                prev_dim = h_dim
        self.feature_extractor = nn.Sequential(*layers)
        self.final_dim = prev_dim
        self.regressor = nn.Sequential(
        nn.Linear(self.final_dim, 256),   # 确保这里的 self.final_dim 与 checkpoint 匹配
        nn.GELU(),
        nn.Dropout(0.4),          
        nn.LayerNorm(256),        
        nn.Linear(256, 128),              # 对应报错中的 regressor.4，输出 128
        nn.GELU(),
        nn.Dropout(0.3),          
        nn.Linear(128, 1)                 # 对应报错中的 regressor.7，输出 1
    )
        self.lig_proj = nn.Sequential(nn.Linear(prev_dim, 512), nn.GELU(), nn.Dropout(dropout_rate), nn.LayerNorm(512), nn.Linear(512, lig_dim))
        self.pkt_proj = nn.Sequential(nn.Linear(prev_dim, 512), nn.GELU(), nn.Dropout(dropout_rate), nn.LayerNorm(512), nn.Linear(512, pkt_dim))
        self.attn_proj = nn.Sequential(nn.Linear(prev_dim, 1024), nn.GELU(), nn.Dropout(dropout_rate), nn.LayerNorm(1024), nn.Linear(1024, attn_layers * attn_dim * attn_dim))
        self.self_attn = nn.MultiheadAttention(embed_dim=prev_dim, num_heads=8, dropout=0.1, batch_first=True)
        self.attn_norm = nn.LayerNorm(prev_dim)

    def forward(self, x, return_intermediate=False):
        features = self.feature_extractor(x)
        attn_out, _ = self.self_attn(features.unsqueeze(1), features.unsqueeze(1), features.unsqueeze(1))
        features = self.attn_norm(features + attn_out.squeeze(1))
        return self.regressor(features).squeeze(1)

class InferenceDataset(Dataset):
    def __init__(self, features): self.features = features
    def __len__(self): return len(self.features)
    def __getitem__(self, idx): return torch.tensor(self.features[idx], dtype=torch.float32)

def get_fast_embeddings(smiles_list, model_name="./molformer_local", batch_size=512):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    model = AutoModel.from_pretrained(model_name, deterministic_eval=True, trust_remote_code=True).to(device)
    model.eval()
    embeddings = []
    with torch.no_grad():
        for i in tqdm(range(0, len(smiles_list), batch_size), desc="极速提取 MoLFormer 特征"):
            inputs = tokenizer(smiles_list[i:i+batch_size], return_tensors="pt", padding=True, truncation=True, max_length=128).to(device)
            emb = model(**inputs).last_hidden_state[:, 0, :].cpu().numpy()
            embeddings.append(emb)
    return np.concatenate(embeddings, axis=0)

def main():
    setup_logger()
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_dir", required=True)
    parser.add_argument("--smiles_file", required=True)
    parser.add_argument("--output_csv", default="predictions_output.csv")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    
    # === 1. 严格清洗数据 ===
    df = pd.read_csv(args.smiles_file)
    initial_len = len(df)
    valid_indices = []
    
    logging.info("🧹 正在检查并清洗外部测试集的 SMILES...")
    for i, smi in enumerate(df['SMILES']):
        if isinstance(smi, str) and pd.notna(smi) and Chem.MolFromSmiles(smi) is not None:
            valid_indices.append(i)
            
    df = df.iloc[valid_indices].reset_index(drop=True)
    logging.info(f"清洗完毕: 保留了 {len(df)} 个有效分子 (剔除 {initial_len - len(df)} 个)。")

    # === 2. 提取特征并推理 (包含精准计时) ===
    logging.info("开始执行高通量特征提取与推理...")
    start_time = time.time()  # 🌟 核心计时开始

    embeddings = get_fast_embeddings(df["SMILES"].tolist(), batch_size=512)
    checkpoint = torch.load(os.path.join(args.model_dir, "best_model.pth"), map_location=device, weights_only=False)
    desc_scaler, label_scaler = checkpoint['desc_scaler'], checkpoint['label_scaler']
    features_scaled = desc_scaler.transform(embeddings)

    import json
    with open(os.path.join(args.model_dir, 'model_config.json'), 'r') as f: config = json.load(f)
    model = EnhancedStudentModel(in_dim=config['in_dim'], lig_dim=config['lig_dim'], pkt_dim=config['pkt_dim'], attn_layers=config['attn_layers'], attn_dim=config['attn_dim'], hidden_dims=config['hidden_dims'], dropout_rate=config['dropout_rate']).to(device)
    model.load_state_dict(checkpoint['model_state_dict'])
    model.eval()

    dataset = InferenceDataset(features_scaled)
    loader = DataLoader(dataset, batch_size=1024, shuffle=False, num_workers=4)

    preds_scaled = []
    with torch.no_grad():
        for batch_x in tqdm(loader, desc="模型预测"):
            preds_scaled.append(model(batch_x.to(device)).cpu().numpy())

    end_time = time.time()  # 🌟 核心计时结束
    
    # === 时间与算力压测计算 ===
    total_time = end_time - start_time
    throughput = len(df) / total_time if total_time > 0 else 0  # 吞吐量 (分子/秒)
    capacity_24h = throughput * 3600 * 24  # 24小时极限产能预测

    # 格式化总耗时输出 (小时:分钟:秒)
    m, s = divmod(total_time, 60)
    h, m = divmod(m, 60)
    time_str = f"{int(h)}小时 {int(m)}分钟 {s:.2f}秒"

    preds_orig = label_scaler.inverse_transform(np.concatenate(preds_scaled).reshape(-1, 1)).squeeze()
    
    # === 3. 计算指标并输出报告 ===
    true_orig = df['Affinity'].values
    r2 = max(0, r2_score(true_orig, preds_orig))
    spearman = spearmanr(true_orig, preds_orig)[0]
    
    logging.info("\n" + "="*55)
    logging.info("外部独立测试集 打榜与压测报告 (External Validation)")
    logging.info("="*55)
    logging.info(f"样本量 (N)      : {len(df):,}")
    logging.info(f"总耗时 (Time)   : {time_str}")
    logging.info(f"预测速度 (Spd)  : {throughput:.2f} 分子/秒")
    logging.info(f"24h 极限产能    : 约 {capacity_24h:,.0f} 个分子 / 天")
    logging.info("-" * 55)
    logging.info(f"Spearman 排序   : {spearman:.4f}")
    logging.info(f"R² 绝对精度     : {r2:.4f}")
    logging.info("="*55)

    # 追加预测列并保存
    df["Predicted_Affinity"] = preds_orig
    df.to_csv(args.output_csv, index=False)
    logging.info(f"完整预测结果已保存至: {args.output_csv} (已跳过画图)")

if __name__ == "__main__":
    main()