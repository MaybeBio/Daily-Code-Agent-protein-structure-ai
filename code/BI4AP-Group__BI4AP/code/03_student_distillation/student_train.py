# student_kd_cmad_train.py
import math
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import pickle
import argparse
import logging
import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.feature_selection import SelectFromModel
from sklearn.ensemble import RandomForestRegressor
from transformers import RobertaTokenizer, RobertaModel, AutoTokenizer, AutoModel
from torch.utils.data import Dataset
import torch.nn.functional as F
import json
from scipy.stats import pearsonr, spearmanr
from rdkit import Chem
from rdkit.Chem import AllChem
import matplotlib.pyplot as plt
import seaborn as sns
from tqdm import tqdm

# ========= Config ========= #
BATCH_SIZE = 256
EPOCHS = 300  # 增加最大训练轮数
PATIENCE = 10  # 增加早停耐心值
LR = 1e-4
VAL_RATIO = 0.15
TEST_RATIO = 0.15
NUM_WORKERS = 2

# ========= Utilities ========= #
def set_seed(seed):
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    np.random.seed(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def setup_logger(log_path):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler()]
    )


import time
from datetime import datetime


def plot_val_distribution(out_dir, val_labels_orig, val_preds_orig, suffix=""):
    """绘制验证集真实值与预测值的分布对比图"""
    try:
        # 设置样式
        sns.set_style("whitegrid")


        # 创建图表
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

        # 绘制真实值分布
        sns.histplot(val_labels_orig, bins=30, color='blue', label='True', alpha=0.5, ax=ax1)
        ax1.set_title('True Values Distribution')
        ax1.set_xlabel('Affinity')
        ax1.set_ylabel('Frequency')

        # 绘制预测值分布
        sns.histplot(val_preds_orig, bins=30, color='red', label='Pred', alpha=0.5, ax=ax2)
        ax2.set_title('Predicted Values Distribution')
        ax2.set_xlabel('Affinity')
        ax2.set_ylabel('Frequency')

        plt.tight_layout()

        # 生成唯一文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f'val_distribution_check_{timestamp}{suffix}.png'
        plt.savefig(os.path.join(out_dir, filename), dpi=300, bbox_inches='tight')
        plt.close()

        logging.info(f"验证集分布对比图已保存: {filename}")
    except Exception as e:
        logging.warning(f"绘制分布对比图失败: {e}")


def plot_correlation(out_dir, true_values, pred_values, set_name):
    plt.figure(figsize=(8, 8))

    # 计算回归线
    z = np.polyfit(true_values, pred_values, 1)
    p = np.poly1d(z)

    # 绘制散点图
    plt.scatter(true_values, pred_values, alpha=0.6, s=30)

    # 绘制回归线
    plt.plot(true_values, p(true_values), "r--", alpha=0.8,
             label=f'y = {z[0]:.3f}x + {z[1]:.3f}')

    # 绘制理想线
    min_val = min(min(true_values), min(pred_values))
    max_val = max(max(true_values), max(pred_values))
    plt.plot([min_val, max_val], [min_val, max_val], 'g-', alpha=0.5, label='Ideal')

    # 计算指标
    mae = mean_absolute_error(true_values, pred_values)
    rmse = np.sqrt(mean_squared_error(true_values, pred_values))
    r2 = r2_score(true_values, pred_values)
    pearson = pearsonr(true_values, pred_values)[0]

    # 添加文本框
    textstr = '\n'.join((
        f'MAE = {mae:.3f}',
        f'RMSE = {rmse:.3f}',
        f'R² = {r2:.3f}',
        f'Pearson = {pearson:.3f}'))

    props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)
    plt.gca().text(0.05, 0.95, textstr, transform=plt.gca().transAxes, fontsize=10,
                   verticalalignment='top', bbox=props)

    plt.xlabel('True Values')
    plt.ylabel('Predicted Values')
    plt.title(f'True vs Predicted ({set_name})')
    plt.legend(loc='lower right')
    plt.grid(True, alpha=0.3)

    plt.savefig(os.path.join(out_dir, f'correlation_{set_name}.png'), dpi=300, bbox_inches='tight')
    plt.close()
# ========= Dataset ========= #
class StudentDatasetKDEnhanced(Dataset):
    def __init__(self, df, knowledge_df, precomputed_features, desc_scaler, label_scaler, mode="train" ,add_noise=False):
        self.df = df.reset_index(drop=True)
        self.knowledge = knowledge_df
        self.mode = mode
        self.label_scaler = label_scaler
        self.add_noise = add_noise
        # 直接使用传入并已缩放好的特征，因为外面已经全局清洗并GPU提取过了，不再做任何多余的过滤或提取！
        self.features = desc_scaler.transform(precomputed_features)
        
        # 标准化真实标签
        self.labels = label_scaler.transform(self.df[["Affinity"]]).squeeze()
        self.valid_indices = list(range(len(self.df)))

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        smi = self.df.iloc[idx]["SMILES"]
        key = self.df.iloc[idx]["Filename"]
        feature = torch.tensor(self.features[idx], dtype=torch.float32)
        label = torch.tensor(self.labels[idx], dtype=torch.float32)

        if self.mode == "train" and self.add_noise:
            noise = torch.randn_like(feature) * 0.05
            feature = feature + noise
        
        if self.mode == "test":
            sample = self.knowledge.iloc[0]
            lig_dim = len(sample["LigandVector"])
            pkt_dim = len(sample["PocketVector"])
            attn_dim = len(sample["AttentionMaps"])
            return (feature,
                    torch.zeros(lig_dim),
                    torch.zeros(pkt_dim),
                    torch.zeros(attn_dim),
                    label)

        lig_vec = torch.tensor(self.knowledge.loc[self.knowledge["Filename"] == key, "LigandVector"].values[0], dtype=torch.float32)
        pkt_vec = torch.tensor(self.knowledge.loc[self.knowledge["Filename"] == key, "PocketVector"].values[0], dtype=torch.float32)
        
        attn_list = self.knowledge.loc[self.knowledge["Filename"] == key, "AttentionMaps"].values[0] 
        attn_array = np.stack(attn_list, axis=0) 
        attn_tensor = torch.from_numpy(attn_array).float()

        return feature, lig_vec, pkt_vec, attn_tensor, label


# ========= Model ========= #
class ResidualBlock(nn.Module):
    """残差块模块"""

    def __init__(self, dim, dropout_rate=0.2):
        super().__init__()
        self.block = nn.Sequential(
            nn.Linear(dim, dim),
            nn.GELU(),
            nn.Dropout(dropout_rate),
            nn.Linear(dim, dim)
        )
        self.norm = nn.LayerNorm(dim)
        self.dropout = nn.Dropout(dropout_rate)

    def forward(self, x):
        return self.norm(x + self.dropout(self.block(x)))


class EnhancedStudentModel(nn.Module):
    def __init__(self, in_dim, lig_dim, pkt_dim, attn_layers, attn_dim,
                 hidden_dims=[256, 256, 128], dropout_rate=0.5):
        super().__init__()
        self.lig_dim = lig_dim
        self.pkt_dim = pkt_dim
        self.attn_layers = attn_layers  # 教师注意力层数
        self.attn_dim = attn_dim  # 注意力图维度

        # 构建更深的MLP网络，添加残差连接
        layers = []
        prev_dim = in_dim

        # 输入投影层
        layers.append(nn.Linear(prev_dim, hidden_dims[0]))
        layers.append(nn.GELU())
        layers.append(nn.Dropout(dropout_rate))
        layers.append(nn.LayerNorm(hidden_dims[0]))
        prev_dim = hidden_dims[0]

        # 添加多个残差块
        for hidden_dim in hidden_dims[1:]:
            layers.append(ResidualBlock(prev_dim, dropout_rate))
            if hidden_dim != prev_dim:
                layers.append(nn.Linear(prev_dim, hidden_dim))
                layers.append(nn.GELU())
                layers.append(nn.Dropout(dropout_rate))
                layers.append(nn.LayerNorm(hidden_dim))
                prev_dim = hidden_dim

        # 最终特征提取层
        self.feature_extractor = nn.Sequential(*layers)
        self.final_dim = prev_dim

        # 输出层
        # ================= 新增：双线性交互层 =================
        self.interaction_dim = 256  # 设定一个共享的交互隐空间维度
        
        # 将结构对齐后的配体和口袋特征，投影到同一维度的交互空间
        self.W_lig_int = nn.Sequential(
            nn.Linear(lig_dim, self.interaction_dim),
            nn.LayerNorm(self.interaction_dim)
        )
        self.W_pkt_int = nn.Sequential(
            nn.Linear(pkt_dim, self.interaction_dim),
            nn.LayerNorm(self.interaction_dim)
        )
        
        # 极度精简的最终回归头：输入是双线性交互后的特征
        # 减少层数和参数量，强制模型依赖交互质量而非MLP的拟合能力
        self.regressor = nn.Sequential(
            nn.Linear(self.interaction_dim, 64),
            nn.GELU(),
            nn.Dropout(0.3),
            nn.LayerNorm(64),
            nn.Linear(64, 1)
        )
        # ===================================================

        # 添加所有需要的投影头
        self.lig_proj = nn.Sequential(
            nn.Linear(self.final_dim, 512),
            nn.GELU(),
            nn.Dropout(dropout_rate),
            nn.LayerNorm(512),
            nn.Linear(512, lig_dim)
        )

        self.pkt_proj = nn.Sequential(
            nn.Linear(self.final_dim, 512),
            nn.GELU(),
            nn.Dropout(dropout_rate),
            nn.LayerNorm(512),
            nn.Linear(512, pkt_dim)
        )

        # 注意力投影层 - 使用更高效的设计
        self.attn_proj = nn.Sequential(
            nn.Linear(self.final_dim, 1024),
            nn.GELU(),
            nn.Dropout(dropout_rate),
            nn.LayerNorm(1024),
            nn.Linear(1024, attn_layers * attn_dim * attn_dim),
        )

        # 添加简单的注意力机制
        self.self_attn = nn.MultiheadAttention(
            embed_dim=self.final_dim,
            num_heads=8,
            dropout=0.1,
            batch_first=True
        )
        self.attn_norm = nn.LayerNorm(self.final_dim)

    def forward(self, x, return_intermediate=False):
        # 1. 基础特征提取
        features = self.feature_extractor(x)

        # 2. 应用自注意力增强全局序列特征
        attn_out, _ = self.self_attn(
            features.unsqueeze(1),
            features.unsqueeze(1),
            features.unsqueeze(1)
        )
        features = self.attn_norm(features + attn_out.squeeze(1))

        # 3. 提取结构感知的子特征 (用于蒸馏)
        lig_pred = self.lig_proj(features)
        pkt_pred = self.pkt_proj(features)

        # 4. 双线性融合 (Bilinear Fusion) - 核心物理意义模块
        # 将特征投影至同一维度并使用 Sigmoid 激活，表示局部特征的激活强度
        lig_int = torch.sigmoid(self.W_lig_int(lig_pred))
        pkt_int = torch.sigmoid(self.W_pkt_int(pkt_pred))
        
        # 元素级乘积 (Hadamard Product)：模拟配体与口袋的空间互作
        # 只有当配体和口袋在同一个隐维度上都高度激活时，交互特征才强烈
        interaction_feat = lig_int * pkt_int 

        # 5. 最终亲和力回归
        output = self.regressor(interaction_feat).squeeze(1)

        if return_intermediate:
            # 处理注意力预测
            attn_flat = self.attn_proj(features)
            attn_pred = attn_flat.view(-1, self.attn_layers, self.attn_dim, self.attn_dim)
            return output, (lig_pred, pkt_pred, attn_pred), features

        return output


# ========= Loss ========= #
class InfoNCELoss(nn.Module):
    def __init__(self, temperature=0.1):
        """
        temperature: 温度超参数，通常设为 0.1 左右。
        值越小，模型对区分困难负样本的惩罚越大。
        """
        super().__init__()
        self.temperature = temperature

    def forward(self, student_feat, teacher_feat):
        # 1. 对特征进行 L2 归一化，使其映射到单位超球面上
        s_norm = F.normalize(student_feat, p=2, dim=-1)
        t_norm = F.normalize(teacher_feat, p=2, dim=-1)
        
        # 2. 计算批次内所有学生与所有教师的相似度矩阵
        # 结果是一个 [batch_size, batch_size] 的矩阵
        # 矩阵的第 i 行第 j 列代表：第 i 个学生特征与第 j 个教师特征的余弦相似度
        logits = torch.matmul(s_norm, t_norm.T) / self.temperature
        
        # 3. 构造标签：正样本位于相似度矩阵的对角线上（即第 i 个学生对应第 i 个教师）
        batch_size = student_feat.size(0)
        labels = torch.arange(batch_size).long().to(student_feat.device)
        
        # 4. 使用交叉熵计算损失
        loss = F.cross_entropy(logits, labels)
        
        return loss
    

class SimpleMSELoss(nn.Module):
    def __init__(self, alpha=1.0, beta=0.1, gamma=0.1):
        super().__init__()
        self.mse = nn.MSELoss()
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma

    def forward(self, pred, target, student_reps, teacher_reps):
        # 主损失
        loss_main = self.mse(pred, target)

        # 向量对齐损失
        lig_loss = self.mse(student_reps[0], teacher_reps["ligand_vec"])
        pkt_loss = self.mse(student_reps[1], teacher_reps["pocket_vec"])
        loss_vec = lig_loss + pkt_loss

        # 注意力对齐损失 - 对每个样本的每层注意力计算损失
        attn_loss = 0
        batch_size = teacher_reps["attentions"].shape[0]

        for i in range(batch_size):
            for layer_idx in range(teacher_reps["attentions"].shape[1]):
                s_attn = student_reps[2][i, layer_idx]  # 学生注意力图
                t_attn = teacher_reps["attentions"][i, layer_idx]  # 教师注意力图
                attn_loss += self.mse(s_attn, t_attn)

        attn_loss = attn_loss / (batch_size * teacher_reps["attentions"].shape[1])

        # 总损失
        total_loss = (
                self.alpha * loss_main +
                self.beta * loss_vec +
                self.gamma * attn_loss
        )

        metrics = {
            "main": loss_main.item(),
            "lig": lig_loss.item(),
            "pkt": pkt_loss.item(),
            "attn": attn_loss.item(),
            "total": total_loss.item()
        }

        return total_loss, metrics


# ========= Main Training ========= #
# ========= 替换原有的 train_kd_cmad 定义 =========
def train_kd_cmad(data_csv, knowledge_pkl, out_dir,
                  alpha, beta, gamma, temp, fold, 
                  backbone='chemberta', add_noise=False, weight_decay=1e-2, 
                  data_ratio=1.0):   # <-- 确保这里加了这三个参数
    os.makedirs(out_dir, exist_ok=True)
    setup_logger(os.path.join(out_dir, "train.log"))
    set_seed(42 + fold)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # 添加编码处理
    def detect_encoding(file_path):
        import chardet
        with open(file_path, 'rb') as f:
            result = chardet.detect(f.read())
        return result['encoding']

    try:
        data_encoding = detect_encoding(data_csv)
        df = pd.read_csv(data_csv, encoding=data_encoding)
        logging.info(f"检测到数据文件编码: {data_encoding}")
    except Exception as e:
        logging.warning(f"检测编码失败: {e}, 尝试使用latin1编码")
        df = pd.read_csv(data_csv, encoding='latin1')

    with open(knowledge_pkl, "rb") as f:
        knowledge = pd.DataFrame(pickle.load(f))

    # ========= 极其关键：提前清洗脏数据 =========
    # 1. 过滤知识库中不存在的样本
    knowledge_filenames = set(knowledge["Filename"].values)
    df = df[df["Filename"].isin(knowledge_filenames)].reset_index(drop=True)
    
    # 2. 提前过滤无效SMILES（保证后续特征提取和标签完全对齐）
    valid_indices = []
    for idx, row in df.iterrows():
        smi = row["SMILES"]
        if isinstance(smi, str) and not pd.isna(smi) and Chem.MolFromSmiles(smi) is not None:
            valid_indices.append(idx)
            
    df = df.iloc[valid_indices].reset_index(drop=True)
    logging.info(f"清理无效数据并匹配知识库后，最终有效数据集大小: {len(df)}")

    # ================= 🚀 新增：根据 data_ratio 缩减总数据量 =================
    if 0.0 < data_ratio < 1.0:
        from sklearn.model_selection import train_test_split
        try:
            # 尝试分层抽样，保持亲和力分布一致
            affinity_bins_temp = pd.qcut(df["Affinity"], q=10, labels=False, duplicates='drop')
            df, _ = train_test_split(df, train_size=data_ratio, random_state=42, stratify=affinity_bins_temp)
        except Exception as e:
            # 如果样本极少导致无法分层，回退到随机抽样
            df, _ = train_test_split(df, train_size=data_ratio, random_state=42)
        df = df.reset_index(drop=True)
        logging.info(f"📊 数据量压测: 当前使用 {data_ratio*100}% 的数据，有效样本量缩减至 {len(df)}")
    # ====================================================================

    # ================= 🚀 核心修改：5折交叉验证切分 =================
    from sklearn.model_selection import StratifiedKFold, StratifiedShuffleSplit
    
    # 按照亲和力分位数生成分层标签
    affinity_bins = pd.qcut(df["Affinity"], q=10, labels=False, duplicates='drop')
    
    # 初始化 5折交叉验证 (固定 random_state=42，保证每次跑的折叠划分都是一样的)
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    folds = list(skf.split(df, affinity_bins))
    
    # 根据传入的 fold 参数，获取当前折的 训练+验证集 和 测试集
    train_val_idx, test_idx = folds[fold]
    
    # 从 训练+验证集 中再划出 15% 作为早停用的验证集
    train_val_df = df.iloc[train_val_idx].reset_index(drop=True)
    tv_affinity_bins = pd.qcut(train_val_df["Affinity"], q=10, labels=False, duplicates='drop')
    
    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.15, random_state=42)
    for t_idx, v_idx in sss.split(train_val_df, tv_affinity_bins):
        train_idx_final = train_val_idx[t_idx]
        val_idx_final = train_val_idx[v_idx]
        
    train_df = df.iloc[train_idx_final].reset_index(drop=True)
    val_df = df.iloc[val_idx_final].reset_index(drop=True)
    test_df = df.iloc[test_idx].reset_index(drop=True)
    # ==============================================================

    # 检查数据分布
    logging.info(f"=== 当前执行 5-Fold CV: 第 {fold+1} 折 ===")
    logging.info(f"训练集大小: {len(train_df)} | 验证集大小: {len(val_df)} | 测试集大小: {len(test_df)}")

    # Preprocessing
    label_scaler = StandardScaler().fit(train_df[["Affinity"]])

    # 获取训练集的嵌入特征来拟合 desc_scaler
    def get_fast_embeddings(smiles_list, model_name="./chemberta_zinc", batch_size=256):
        """GPU加速的批量ChemBERTa特征提取"""
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logging.info(f"正在 {device} 上加速提取 ChemBERTa 特征...")

        if backbone == 'molformer':
            model_name = "./molformer_local"
            tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
            model = AutoModel.from_pretrained(model_name, deterministic_eval=True, trust_remote_code=True).to(device)
        else:
            model_name = "./chemberta_zinc"
            tokenizer = RobertaTokenizer.from_pretrained(model_name)
            model = RobertaModel.from_pretrained(model_name).to(device)
        model.eval()

        embeddings = []
        from tqdm import tqdm
        with torch.no_grad():
            for i in tqdm(range(0, len(smiles_list), batch_size), desc=f"提取SMILES特征 ({backbone})"):
                batch_smiles = smiles_list[i:i+batch_size]
                valid_smiles = [s if isinstance(s, str) and not pd.isna(s) else "C" for s in batch_smiles]
                
                inputs = tokenizer(valid_smiles, return_tensors="pt", padding=True, truncation=True, max_length=128).to(device)
                outputs = model(**inputs)
                
                # MolFormer 和 ChemBERTa 都可以取 pooler_output 或 sequence 的均值，这里统一取 CLS token
                emb = outputs.last_hidden_state[:, 0, :].cpu().numpy()
                embeddings.append(emb)
                
        return np.concatenate(embeddings, axis=0)
    

    all_smiles = df["SMILES"].tolist()
    all_embeddings = get_fast_embeddings(all_smiles)
    
    
    # 拆分特征
    train_embeddings = all_embeddings[train_idx_final]
    val_embeddings = all_embeddings[val_idx_final]
    test_embeddings = all_embeddings[test_idx]
    
    # 拟合 Scaler
    desc_scaler = StandardScaler().fit(train_embeddings)
    label_scaler = StandardScaler().fit(train_df[["Affinity"]])
    
    # Init dataset (直接传入算好的 embeddings)
    train_ds = StudentDatasetKDEnhanced(train_df, knowledge, train_embeddings, desc_scaler, label_scaler, mode="train", add_noise=add_noise)
    val_ds = StudentDatasetKDEnhanced(val_df, knowledge, val_embeddings, desc_scaler, label_scaler, mode="val")
    test_ds = StudentDatasetKDEnhanced(test_df, knowledge, test_embeddings, desc_scaler, label_scaler, mode="test")
    # ---------------- 替换这里结束 ----------------

    # 检查数据集大小
    logging.info(f"训练数据集有效样本: {len(train_ds)}")
    logging.info(f"验证数据集有效样本: {len(val_ds)}")
    logging.info(f"测试数据集有效样本: {len(test_ds)}")

    if len(train_ds) == 0:
        logging.error("训练数据集为空，无法继续训练")
        return

    # 创建数据加载器
    # 🚀 修复极小数据量压测时的“吞数据”问题
    # 如果当前数据量连一个 BATCH_SIZE 都凑不齐，就动态缩小 BATCH_SIZE
    actual_batch_size = min(BATCH_SIZE, max(1, len(train_ds)))
    
    # 将 drop_last 改为 False，确保在 1% 数据量时仅有的几十个样本绝不会被丢弃
    train_loader = DataLoader(train_ds, actual_batch_size, shuffle=True, num_workers=NUM_WORKERS,
                              pin_memory=True, drop_last=False)
    val_loader = DataLoader(val_ds, BATCH_SIZE, shuffle=False, num_workers=NUM_WORKERS,
                            pin_memory=True)
    test_loader = DataLoader(test_ds, BATCH_SIZE, shuffle=False, num_workers=NUM_WORKERS,
                             pin_memory=True)

    # Init model
    sample = knowledge.iloc[0]
    num_attn_layers = len(sample["AttentionMaps"])
    lig_dim = len(sample["LigandVector"])
    pkt_dim = len(sample["PocketVector"])
    attn_dim = sample["AttentionMaps"][0].shape[0]  # 假设是方阵

    logging.info(f"教师向量维度 - Ligand: {lig_dim}, Pocket: {pkt_dim}")
    logging.info(f"教师注意力 - 层数: {num_attn_layers}, 维度: {attn_dim}")

    # 网络结构
    model = EnhancedStudentModel(
        in_dim=train_ds.features.shape[1],
        lig_dim=lig_dim,
        pkt_dim=pkt_dim,
        attn_layers=num_attn_layers,
        attn_dim=attn_dim,
        hidden_dims=[512, 512, 256, 128],  
        dropout_rate=0.4  
    ).to(device)

    # 优化器配置
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=LR,
        weight_decay=weight_decay,  # 使用传入的参数
        eps=1e-8
    )

    # 余弦退火学习率调度
    from torch.optim.lr_scheduler import CosineAnnealingLR

    scheduler = CosineAnnealingLR(
        optimizer, T_max=EPOCHS, eta_min=1e-6
    )

    # 损失函数，增加动态权重调整
    # 损失函数，结合退火策略与余弦相似度“软对齐”
    class DynamicMSELoss(nn.Module):
        def __init__(self, alpha=1.0, beta=1.0, gamma=0.1, phase1_epochs=20):
            super().__init__()
            self.mse = nn.MSELoss()
            # 替换为 InfoNCE 损失，引入温度系数 0.1 (对标顶刊常用设置)
            self.info_nce_loss = InfoNCELoss(temperature=0.1) 
            self.base_alpha = alpha
            self.base_beta = beta
            self.base_gamma = gamma
            self.phase1_epochs = phase1_epochs
            self.current_epoch = 0

        def update_epoch(self, epoch):
            self.current_epoch = epoch

        def forward(self, pred, target, student_reps, teacher_reps):
            # 1. 动态权重退火策略 (Two-Stage Annealing)
            if self.current_epoch <= self.phase1_epochs:
                # 【第一阶段：模仿期】
                # Alpha (亲和力) 缓慢从 0 爬升，让模型前期专心模仿教师的向量空间
                progress = self.current_epoch / self.phase1_epochs
                curr_alpha = self.base_alpha * progress
                curr_beta = self.base_beta
                curr_gamma = self.base_gamma
            else:
                # 【第二阶段：做题期】
                # Alpha 火力全开；Beta (向量) 砍掉 90%；Gamma (注意力) 砍掉 99%
                # 相当于老师放手，让学生自己悟
                curr_alpha = self.base_alpha
                curr_beta = self.base_beta * 0.1
                curr_gamma = self.base_gamma * 0.01

            # 2. 主任务损失 (亲和力)
            loss_main = self.mse(pred, target)

            # 3. 向量对齐损失 (全面升级为对比学习 InfoNCE)
            # 自动利用同一个 Batch 内的其它样本作为负样本，防止特征坍缩
            lig_loss = self.info_nce_loss(student_reps[0], teacher_reps["ligand_vec"])
            pkt_loss = self.info_nce_loss(student_reps[1], teacher_reps["pocket_vec"])
            loss_vec = lig_loss + pkt_loss

            # 4. 注意力对齐损失 (池化降维，极度松绑)
            # 不再逐像素要求 400x400 一模一样，而是在最后一个维度求均值，只对齐注意力分布的“整体轮廓”
            s_attn_pooled = student_reps[2][:, -1].mean(dim=-1)
            # 确保教师注意力转为 float32 防止精度报错
            t_attn_pooled = teacher_reps["attentions"][:, -1].float().mean(dim=-1) 
            loss_attn = self.mse(s_attn_pooled, t_attn_pooled)

            # 5. 总损失融合
            total_loss = (
                    curr_alpha * loss_main +
                    curr_beta * loss_vec +
                    curr_gamma * loss_attn
            )

            metrics = {
                "main": loss_main.item(),
                "lig": lig_loss.item(),
                "pkt": pkt_loss.item(),
                "attn": loss_attn.item(),
                "total": total_loss.item(),
                "curr_alpha": curr_alpha,
                "curr_beta": curr_beta,
                "curr_gamma": curr_gamma
            }

            return total_loss, metrics

    criterion = DynamicMSELoss(alpha=alpha, beta=beta, gamma=gamma, phase1_epochs=20)

    # Train loop
    best_score, best_epoch, no_improve = -np.inf, -1, 0
    train_history = []
    val_history = []
    train_loss_history = []
    val_mae_history = []
    val_rmse_history = []
    val_r2_history = []
    val_pearson_history = []
    val_spearman_history = []

    for epoch in range(1, EPOCHS + 1):
        criterion.update_epoch(epoch)

        model.train()
        train_losses = []
        train_metrics = {"main": [], "lig": [], "pkt": [], "attn": [], "curr_alpha": [], "curr_beta": [], "curr_gamma": []}

        for step_idx, (x, lig_vec, pkt_vec, attn, label) in enumerate(train_loader):
            x = x.to(device, non_blocking=True)
            lig_vec = lig_vec.to(device, non_blocking=True)
            pkt_vec = pkt_vec.to(device, non_blocking=True)
            attn = attn.to(device, non_blocking=True)
            label = label.to(device, non_blocking=True)

            # 前向传播
            pred, (lig_pred, pkt_pred, attn_pred), _ = model(x, return_intermediate=True)

            # 创建教师数据字典
            teacher_data = {
                "ligand_vec": lig_vec,
                "pocket_vec": pkt_vec,
                "attentions": attn,
                "soft_label": label
            }

            # 计算损失
            loss, subm = criterion(
                pred,
                label,
                (lig_pred, pkt_pred, attn_pred),
                teacher_data
            )

            train_losses.append(loss.item())
            for k in train_metrics:
                train_metrics[k].append(subm[k])

            # 反向传播
            optimizer.zero_grad()
            loss.backward()

            # 梯度裁剪
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)

            optimizer.step()

        # 更新学习率
        scheduler.step()
        current_lr = optimizer.param_groups[0]['lr']

        # 验证阶段
        model.eval()
        val_preds_scaled, val_labels_scaled = [], []
        with torch.no_grad():
            for x, _, _, _, label in val_loader:
                x, label = x.to(device), label.to(device)
                pred = model(x)
                val_preds_scaled.append(pred.cpu().numpy())
                val_labels_scaled.append(label.cpu().numpy())

        # 计算验证指标
        val_preds_scaled = np.concatenate(val_preds_scaled)
        val_labels_scaled = np.concatenate(val_labels_scaled)

        val_preds_orig = label_scaler.inverse_transform(val_preds_scaled.reshape(-1, 1)).squeeze()
        val_labels_orig = label_scaler.inverse_transform(val_labels_scaled.reshape(-1, 1)).squeeze()

        mae = mean_absolute_error(val_labels_orig, val_preds_orig)
        rmse = np.sqrt(mean_squared_error(val_labels_orig, val_preds_orig))
        r2 = r2_score(val_labels_orig, val_preds_orig)

        # 确保R²非负
        r2 = max(0, r2)

        score = 0.4 * (1.0 / (mae + 1e-8)) + 0.6 * r2

        # 记录历史
        train_history.append(np.mean(train_losses))
        val_history.append(score)

        # 记录训练指标
        avg_metrics = {k: np.mean(v) for k, v in train_metrics.items()}

        logging.info(
            f"Epoch {epoch} | LR: {current_lr:.2e} | TrainLoss: {np.mean(train_losses):.4f} | "
            f"MAE: {mae:.4f} | RMSE: {rmse:.4f} | R2: {r2:.4f} | SCORE: {score:.6f}"
        )
        logging.info(
            f"Weights [a:{avg_metrics['curr_alpha']:.2f}, b:{avg_metrics['curr_beta']:.2f}, g:{avg_metrics['curr_gamma']:.3f}] | "
            f"Losses -> Main: {avg_metrics['main']:.4f}, Vec: {avg_metrics['lig']+avg_metrics['pkt']:.4f}"
        )

        # 记录指标到历史列表
        train_loss_history.append(np.mean(train_losses))
        val_mae_history.append(mae)
        val_rmse_history.append(rmse)
        val_r2_history.append(r2)
        val_pearson_history.append(pearsonr(val_labels_orig, val_preds_orig)[0])
        val_spearman_history.append(spearmanr(val_labels_orig, val_preds_orig)[0])

        # 每10个epoch检查训练集指标
        if epoch % 10 == 0:
            model.eval()
            train_preds, train_labels = [], []
            with torch.no_grad():
                for x, _, _, _, label in train_loader:
                    x, label = x.to(device), label.to(device)
                    pred = model(x)
                    train_preds.append(pred.cpu().numpy())
                    train_labels.append(label.cpu().numpy())

            train_preds = np.concatenate(train_preds)
            train_labels = np.concatenate(train_labels)
            train_preds_orig = label_scaler.inverse_transform(train_preds.reshape(-1, 1)).squeeze()
            train_labels_orig = label_scaler.inverse_transform(train_labels.reshape(-1, 1)).squeeze()

            train_mae = mean_absolute_error(train_labels_orig, train_preds_orig)
            train_r2 = max(0, r2_score(train_labels_orig, train_preds_orig))

            logging.info(f"训练集指标: MAE={train_mae:.4f}, R²={train_r2:.4f}")

        # Early stopping
        # === 动态退火期的阶段性重置 ===
        # 当模型刚刚跨过退火期，进入做题期时，必须清零计分板！
        # 否则之前累积的耐心值会瞬间触发早停。
        if epoch == criterion.phase1_epochs + 1:
            logging.info("退火期结束，进入冲刺阶段！重置早停计数器和最佳分数。")
            best_score = -np.inf
            no_improve = 0

        # === 正常的 Early stopping 逻辑 ===
        if score > best_score + 1e-6:
            best_score = score
            best_epoch = epoch
            no_improve = 0
            # 保存最佳模型
            torch.save({
                'epoch': epoch,
                'model_state_dict': model.state_dict(),
                'optimizer_state_dict': optimizer.state_dict(),
                'best_score': best_score,
                'label_scaler': label_scaler,
                'desc_scaler': desc_scaler,
            }, os.path.join(out_dir, 'best_model.pth'))
        else:
            no_improve += 1
            # 只有在冲刺期（Phase 2），才允许触发早停
            if no_improve >= PATIENCE and epoch > criterion.phase1_epochs:
                logging.info(f"Early stopping at epoch {epoch}. Best SCORE: {best_score:.6f} (epoch {best_epoch})")
                break

    # 保存最终结果
    result = {
        "alpha": alpha,
        "beta": beta,
        "gamma": gamma,
        "T": temp,
        "fold": fold,
        "best_score": float(best_score),
        "best_epoch": int(best_epoch),
        "train_history": train_history,
        "val_history": val_history,
        "val_r2_history": val_r2_history,
        "val_spearman_history": val_spearman_history
    }
    with open(os.path.join(out_dir, "result.json"), "w") as f:
        json.dump(result, f, indent=2)

    # 加载最佳模型进行测试
    checkpoint = torch.load(os.path.join(out_dir, 'best_model.pth'), map_location=device, weights_only=False)
    model.load_state_dict(checkpoint['model_state_dict'])
    model.eval()

    # 计算验证集预测（用于绘制分布图）
    val_preds_scaled_dist = []
    val_labels_scaled_dist = []
    with torch.no_grad():
        for x, _, _, _, label in val_loader:
            x = x.to(device)
            pred = model(x)
            val_preds_scaled_dist.append(pred.cpu().numpy())
            val_labels_scaled_dist.append(label.cpu().numpy())

    val_preds_scaled_dist = np.concatenate(val_preds_scaled_dist)
    val_labels_scaled_dist = np.concatenate(val_labels_scaled_dist)

    # 反标准化
    val_preds_orig_dist = label_scaler.inverse_transform(val_preds_scaled_dist.reshape(-1, 1)).squeeze()
    val_labels_orig_dist = label_scaler.inverse_transform(val_labels_scaled_dist.reshape(-1, 1)).squeeze()

    # 绘制验证集分布对比图
    plot_val_distribution(out_dir, val_labels_orig_dist, val_preds_orig_dist, "_val")
    plot_correlation(out_dir, val_labels_orig_dist, val_preds_orig_dist, "validation")

    test_preds_scaled = []
    with torch.no_grad():
        for x, *_ in test_loader:
            x = x.to(device)
            pred = model(x)
            test_preds_scaled.append(pred.cpu().numpy())

    test_preds_scaled = np.concatenate(test_preds_scaled)
    test_preds_orig = label_scaler.inverse_transform(test_preds_scaled.reshape(-1, 1)).squeeze()


    # 保存测试结果
    test_valid_df = test_df.iloc[test_ds.valid_indices].copy()
    test_valid_df["Predicted"] = test_preds_orig
    test_valid_df.to_csv(os.path.join(out_dir, "test_predictions.csv"), index=False)

    test_labels_orig = test_valid_df["Affinity"].values
    plot_correlation(out_dir, test_labels_orig, test_preds_orig, "test")

    # 计算测试指标
    test_labels_orig = test_valid_df["Affinity"].values
    test_mae = mean_absolute_error(test_labels_orig, test_preds_orig)
    test_rmse = np.sqrt(mean_squared_error(test_labels_orig, test_preds_orig))
    test_r2 = max(0, r2_score(test_labels_orig, test_preds_orig))
    test_pearson = pearsonr(test_labels_orig, test_preds_orig)[0]
    test_spearman = spearmanr(test_labels_orig, test_preds_orig)[0]

    logging.info(f"\n测试集综合评估:")
    logging.info(f"MAE={test_mae:.4f}, RMSE={test_rmse:.4f}, R²={test_r2:.4f}")
    logging.info(f"Pearson={test_pearson:.4f}, Spearman={test_spearman:.4f}")

    # 保存测试结果到文件
    test_results = {
        "test_mae": float(test_mae),
        "test_rmse": float(test_rmse),
        "test_r2": float(test_r2),
        "test_pearson": float(test_pearson),
        "test_spearman": float(test_spearman)
    }

    with open(os.path.join(out_dir, "test_results.json"), "w") as f:
        json.dump(test_results, f, indent=2)
    # 保存模型配置（在保存最佳模型的地方）
    model_config = {
        'in_dim': train_ds.features.shape[1],
        'lig_dim': lig_dim,
        'pkt_dim': pkt_dim,
        'attn_layers': num_attn_layers,
        'attn_dim': attn_dim,
        'hidden_dims': [512, 512, 256, 128],
        'dropout_rate': 0.4
    }

    with open(os.path.join(out_dir, 'model_config.json'), 'w') as f:
        json.dump(model_config, f, indent=2)

    # 保存 scalers
    with open(os.path.join(out_dir, 'scalers.pkl'), 'wb') as f:
        pickle.dump({
            'label_scaler': label_scaler,
            'desc_scaler': desc_scaler,
        }, f)

    # 绘制测试集分布对比图
    plot_val_distribution(out_dir, test_labels_orig, test_preds_orig, "_test")

    return best_score


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_csv", required=True)
    parser.add_argument("--knowledge_pkl", required=True)
    parser.add_argument("--out_dir", default="student_kd_cmad_out")
    parser.add_argument("--alpha", type=float, default=1.0)
    parser.add_argument("--beta", type=float, default=1.0)
    parser.add_argument("--gamma", type=float, default=0.0)
    parser.add_argument("--temp", type=float, default=2.0)
    parser.add_argument("--fold", type=int, default=0, help="当前执行的是第几折(0-4)")
    parser.add_argument("--backbone", type=str, choices=['chemberta', 'molformer'], default='chemberta')
    parser.add_argument("--add_noise", action="store_true", help="是否在特征中加入高斯噪声")
    parser.add_argument("--weight_decay", type=float, default=1e-2, help="优化器的正则化强度")
    parser.add_argument("--data_ratio", type=float, default=1.0, help="使用训练数据的比例") # <--- 新增这行

    parser.add_argument("--auto_experiment", action="store_true", help="一键跑完所有数据量和5折CV")
    
    args = parser.parse_args()

    if args.auto_experiment:
        logging.info("开启全自动实验模式：将连续测试 1% 到 100% 数据量对模型性能的影响")
        # 加入 1% (0.01) 和 10% (0.1)
        ratios = [0.01, 0.1, 0.2, 0.4, 0.6, 0.8, 1.0]
        folds = [0, 1, 2, 3, 4]
        
        for r in ratios:
            for f in folds:
                current_out_dir = f"student_kd_out_ratio_{r}_fold_{f}"
                logging.info("\n" + "="*60)
                logging.info(f"正在训练: 比例 {r*100}% | 第 {f+1} 折")
                logging.info("="*60)
                
                train_kd_cmad(
                    data_csv=args.data_csv,
                    knowledge_pkl=args.knowledge_pkl,
                    out_dir=current_out_dir,
                    alpha=args.alpha,
                    beta=args.beta,
                    gamma=args.gamma,
                    temp=args.temp,
                    fold=f,
                    backbone=args.backbone,
                    add_noise=args.add_noise,
                    weight_decay=args.weight_decay,
                    data_ratio=r  # 传入动态比例
                )
                torch.cuda.empty_cache() # 跑完一折释放一次显存
                
        logging.info("🎉 所有比例的交叉验证实验已全部完成！")
    else:
        # 单次运行模式
        train_kd_cmad(
            data_csv=args.data_csv,
            knowledge_pkl=args.knowledge_pkl,
            out_dir=args.out_dir,
            alpha=args.alpha,
            beta=args.beta,
            gamma=args.gamma,
            temp=args.temp,
            fold=args.fold,
            backbone=args.backbone,
            add_noise=args.add_noise,
            weight_decay=args.weight_decay,
            data_ratio=args.data_ratio
        )

