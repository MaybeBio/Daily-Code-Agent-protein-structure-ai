import time
import torch
from torch import nn, optim
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms
from torchvision.models import resnet152, ResNet152_Weights
from PIL import Image
from sklearn.preprocessing import RobustScaler
from sklearn.preprocessing import StandardScaler
import matplotlib.pyplot as plt
import matplotlib
from sklearn.metrics import mean_absolute_error, r2_score, mean_squared_error
from scipy.stats import pearsonr
from scipy.stats import spearmanr
import seaborn as sns
import argparse
import logging
import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem, Draw
import pandas as pd
import os
from sklearn.model_selection import StratifiedShuffleSplit
from rdkit.Chem import rdFingerprintGenerator
from rdkit.DataStructs import ConvertToNumpyArray


try:
    from torch.nn.utils.parametrizations import weight_norm
except ImportError:
    # 兼容旧版 PyTorch
    from torch.nn.utils import weight_norm

# 添加RDKit导入
try:
    from rdkit import Chem
    from rdkit.Chem import AllChem

    RDKIT_AVAILABLE = True
except ImportError:
    logging.warning("RDKit not installed. SMILES features will not be available.")
    RDKIT_AVAILABLE = False


def setup_device():
    """设置训练设备并记录详细信息"""
    if torch.cuda.is_available():
        gpu_count = torch.cuda.device_count()
        logging.info(f"检测到 {gpu_count} 块GPU可用")
        for i in range(gpu_count):
            logging.info(f"GPU {i}: {torch.cuda.get_device_name(i)}")
        device = torch.device('cuda')

    else:
        logging.warning("未检测到可用GPU，将使用CPU")
        device = torch.device('cpu')

    # 验证设备设置
    test_tensor = torch.tensor([1.0])
    logging.info(f"测试张量设备: {test_tensor.to(device).device}")
    return device


MODES = ['baseline', 'mode1', 'mode2', 'mode3', 'mode4', 'mode5']

# 强制使用系统默认字体
matplotlib.rcParams['font.family'] = 'sans-serif'
sns.set_style("whitegrid")


# 日志配置
class SafeLogHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            try:
                self.stream.write(msg + self.terminator)
            except UnicodeEncodeError:
                msg = msg.encode('utf-8', 'ignore').decode('utf-8', 'ignore')
                self.stream.write(msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)


log_file = 'teacher_training.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    handlers=[logging.FileHandler(log_file, encoding='utf-8'), SafeLogHandler()]
)
# 参数配置
DATA_CSV = './merger_aff.csv'
STRUCT_CSV = './merger_str.csv'
ACID_XLSX = './acid.xlsx'
IMAGE_DIR = '../Yolov8/pngiTSF/'
TEACHER_SAVE = './teacher_model.pth'
BATCH_SIZE = 8
LR = 1e-6
EPOCHS = 300
PATIENCE = 30
SEED = 42
IMG_SIZE = 640
TEST_RATIO = 0.15
VAL_RATIO = 0.15
DEVICE = setup_device()
MAX_GRAD_NORM = 1.0  # 梯度裁剪阈值
GRAD_NORM_LOG_INTERVAL = 10  # 梯度范数记录间隔
# 分子指纹参数
FINGERPRINT_SIZE = 1024  # Morgan指纹长度

# —— 生成 SMILES 2D 图像 ——
assert RDKIT_AVAILABLE, "RDKit 导入失败，无法生成分子图像"

# 读取 CSV
try:
    # 尝试多种可能的编码格式
    df = pd.read_csv(DATA_CSV, encoding='utf-8')
except UnicodeDecodeError:
    try:
        df = pd.read_csv(DATA_CSV, encoding='gbk')  # 尝试GBK编码（中文常用）
    except UnicodeDecodeError:
        try:
            df = pd.read_csv(DATA_CSV, encoding='latin-1')  # 尝试Latin-1编码
        except UnicodeDecodeError as e:
            logging.error(f"无法读取CSV文件: {e}")
            raise

# 目标目录
png_dir = './png_smiles/'
os.makedirs(png_dir, exist_ok=True)

# 遍历每一行，生成并保存分子 2D 结构图
for _, row in df.iterrows():
    smi = row['SMILES']
    fname = f"{row['Filename']}"
    outp = os.path.join(png_dir, fname)
    # 如果 SMILES 为空或文件已存在，则跳过
    if not isinstance(smi, str) or os.path.exists(outp):
        continue
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        continue
    # 计算 2D 坐标并绘制
    AllChem.Compute2DCoords(mol)
    try:
        # 创建绘图选项
        from rdkit.Chem.Draw import MolDrawOptions

        draw_options = MolDrawOptions()
        draw_options.bondLineWidth = 2.0  # 增加键的线宽
        draw_options.minFontSize = 14  # 增加原子标签字体大小
        draw_options.maxFontSize = 18

        # 生成高清图像 (1800x1800像素 ≈ 600DPI @ 3英寸)
        Draw.MolToFile(mol, outp, size=(1800, 1800),
                       imageType='png', options=draw_options)

    except Exception as e:
        logging.warning(f"高清绘图失败 {smi}: {e}, 使用标准绘图")
        # 备用方案
        Draw.MolToFile(mol, outp, size=(1200, 1200), imageType='png')
# —— 图像生成结束 ——


# 加载氨基酸属性表
aa_df = pd.read_excel(ACID_XLSX)
acid_col = aa_df.columns[-1]
aa_df.set_index(acid_col, inplace=True)
aa_df.index = aa_df.index.str.strip().str.upper()
aa_df.rename(columns=lambda x: x.strip(), inplace=True)

# 图像变换
transform = transforms.Compose([
    transforms.Resize((IMG_SIZE, IMG_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
])


# SMILES到指纹的转换函数
def smiles_to_fingerprint(
        smiles: str,
        radius: int = 2,
        n_bits: int = 1024,
        include_chirality: bool = False
) -> np.ndarray:
    """使用RDKit生成Morgan指纹，自动过滤非法SMILES"""
    if not smiles or pd.isna(smiles):
        logging.warning("发现空SMILES，已跳过")
        return None  # ⬅️ 直接返回 None

    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            logging.warning(f"非法SMILES，已跳过: {smiles}")
            return None

        gen = rdFingerprintGenerator.GetMorganGenerator(
            radius=radius,
            fpSize=n_bits,
            includeChirality=include_chirality
        )
        bitvect = gen.GetFingerprint(mol)

        arr = np.zeros((n_bits,), dtype=np.int8)
        ConvertToNumpyArray(bitvect, arr)
        return arr.astype(np.float32)

    except Exception as e:
        logging.warning(f"SMILES解析失败: {smiles}, 错误: {e}，已跳过")
        return None



# 自定义Dataset
class TeacherDataset(Dataset):
    def __init__(self, main_df, struct_df, feature_scaler=None, label_scaler=None, transform=None, scale_label=False,
                 mode='mode3'):

        # 合并数据
        self.df = pd.merge(main_df, struct_df, on='Filename', how='left')

        # 确保 Filename 列是字符串类型，并处理 NaN 值
        self.df['Filename'] = self.df['Filename'].astype(str)
        self.df = self.df[self.df['Filename'] != 'nan']  # 移除 NaN 文件名
        self.filenames = self.df['Filename'].tolist()
        self.aff = self.df['Affinity'].values.astype(np.float32).reshape(-1, 1)
        self.smiles = self.df['SMILES'].tolist() if 'SMILES' in self.df.columns else [None] * len(self.df)  # 新增
        self.transform = transform  # 保存变换对象
        self.feature_scaler = feature_scaler or StandardScaler()
        self.scale_label = scale_label
        self.mode = mode
        self.ligand_image_dir = './png_smiles/'
        self.label_scaler = label_scaler or RobustScaler()

        if scale_label:
            if label_scaler is None:
                # 训练集：先 fit 再 transform
                self.aff_scaled = self.label_scaler.fit_transform(self.aff).squeeze()
            else:
                # 验证 / 测试集：直接 transform，保持与训练集一致
                self.aff_scaled = self.label_scaler.transform(self.aff).squeeze()
        else:
            self.aff_scaled = self.aff.squeeze()

        # 把 scaler 带出去
        self.scalers = {
            'feature': self.feature_scaler,
            'label': self.label_scaler
        }

        # 先处理SMILES指纹特征，获取有效样本索引
        valid_idx = list(range(len(self.df)))  # 初始化为所有索引
        fingerprints = None
        if mode in ['baseline', 'mode1', 'mode2', 'mode3', 'mode4', 'mode5']:
            fingerprints = []
            valid_idx = []  # 记录合法SMILES的样本索引
            for i, s in enumerate(self.smiles):
                fp = smiles_to_fingerprint(s)
                if fp is not None:
                    fingerprints.append(fp)
                    valid_idx.append(i)
                else:
                    logging.warning(f"样本 {self.filenames[i]} 的 SMILES 无效，已跳过")

            # 过滤掉无效的样本
            self.df = self.df.iloc[valid_idx].reset_index(drop=True)
            self.filenames = [self.filenames[i] for i in valid_idx]
            self.aff = self.aff[valid_idx]
            self.aff_scaled = self.aff_scaled[valid_idx]
            self.smiles = [self.smiles[i] for i in valid_idx]
            fingerprints = np.array(fingerprints, dtype=np.float32)

        # 现在，用过滤后的self.df来计算其他结构特征
        cols = struct_df.columns.tolist()
        aa_cols = cols[1:21]
        print("读取的第21列是:", cols[21])
        print("读取的第22列是:", cols[22])
        print("读取的第23列是:", cols[23])
        h_arr = self.df[cols[21]].values.astype(np.float32).reshape(-1, 1)
        bh_arr = self.df[cols[22]].values.astype(np.float32).reshape(-1, 1)
        ww_arr = self.df[cols[23]].values.astype(np.float32).reshape(-1, 1)
        counts = self.df[aa_cols].values.astype(np.float32)

        # 计算水性、pI、分子量
        aa_norm = [c.strip().upper() for c in aa_cols]
        hydro = counts.dot(aa_df['Hydrophobicity'].loc[aa_norm].values).reshape(-1, 1)
        pI = counts.dot(aa_df['pI'].loc[aa_norm].values).reshape(-1, 1)
        mw = counts.dot(aa_df['MW'].loc[aa_norm].values).reshape(-1, 1)

        # === 根据模式构建结构特征 ===
        struct_features = []
        # mode1不使用acid.xlsx属性，仅使用struct_df的counts等
        if mode in ['mode2', 'mode3', 'mode4', 'mode5']:
            struct_features.extend([hydro, pI, mw])
        if mode in ['mode1', 'mode2', 'mode3', 'mode4', 'mode5']:
            struct_features.extend([counts, h_arr, bh_arr, ww_arr])

        # 添加SMILES指纹特征到所有模式
        if mode in ['baseline', 'mode1', 'mode2', 'mode3', 'mode4', 'mode5']:
            struct_features.append(fingerprints)


        # 合并所有结构特征
        if struct_features:
            self.struct_feats = np.hstack(struct_features)
        else:
            self.struct_feats = np.zeros((len(self.df), 0), dtype=np.float32)

        # 特征缩放处理
        if self.struct_feats.shape[1] > 0:
            if feature_scaler is None:
                self.struct_feats = self.feature_scaler.fit_transform(self.struct_feats)
            else:
                # 确保缩放器特征数量匹配
                if feature_scaler.n_features_in_ != self.struct_feats.shape[1]:
                    raise ValueError(
                        f"缩放器期望 {feature_scaler.n_features_in_} 个特征，"
                        f"但得到 {self.struct_feats.shape[1]} 个特征")
                self.feature_scaler = feature_scaler
                self.struct_feats = self.feature_scaler.transform(self.struct_feats)
        else:
            # 基线模式特殊处理
            if feature_scaler is None:
                self.feature_scaler.fit(np.array([[0]]))  # 虚拟拟合

        # 记录原始标签（用于分析）
        self.orig_aff = self.aff.squeeze()
        self._forward_count = 0
        self._log_interval = 10

    def __len__(self):
        return len(self.df)

    # 在 TeacherDataset 的 __getitem__ 方法中，修改以下部分：

    def __getitem__(self, idx):
        # 确保 filename 是字符串类型
        filename = str(self.filenames[idx]) if self.filenames[idx] is not None else "default.png"

        img_path = os.path.join(IMAGE_DIR, filename)

        try:
            img = Image.open(img_path).convert('RGB')
        except Exception as e:
            logging.warning(f"无法加载图片 {img_path}: {e}, 使用替代策略")
            # 尝试使用同一目录下的其他有效图像
            valid_files = [f for f in os.listdir(IMAGE_DIR)
                           if f.endswith('.png') and os.path.exists(os.path.join(IMAGE_DIR, f))]

            if valid_files:
                # 随机选择一个有效图像作为替代
                replacement = np.random.choice(valid_files)
                replacement_path = os.path.join(IMAGE_DIR, replacement)
                try:
                    img = Image.open(replacement_path).convert('RGB')
                    logging.info(f"使用替代图像: {replacement}")
                except:
                    # 如果替代图像也失败，创建白色背景图像
                    img = Image.new('RGB', (IMG_SIZE, IMG_SIZE), (255, 255, 255))
            else:
                # 没有有效图像时创建白色背景
                img = Image.new('RGB', (IMG_SIZE, IMG_SIZE), (255, 255, 255))
        img_complex = self.transform(img) if self.transform else transform(img)

        # === 加载配体图像 ===
        ligand_path = os.path.join(self.ligand_image_dir, filename)  # 使用相同的文件名
        try:
            ligand_img = Image.open(ligand_path).convert('RGB')
        except Exception as e:
            logging.warning(f"无法加载配体图像 {ligand_path}: {e}, 使用空白图像")
            ligand_img = Image.new('RGB', (IMG_SIZE, IMG_SIZE), (255, 255, 255))
        img_ligand = self.transform(ligand_img) if self.transform else transform(ligand_img)

        struct = torch.tensor(self.struct_feats[idx], dtype=torch.float32)
        y = torch.tensor(self.aff_scaled[idx], dtype=torch.float32)

        # === 返回双图像 ===
        if self.mode == 'mode4':
            return img_complex, img_ligand, struct, y
        else:
            return img_complex, struct, y, torch.tensor(0.0)  # 添加一个占位符


# 残差块
class ResidualBlock(nn.Module):
    def __init__(self, dim):
        super().__init__()
        self.block = nn.Sequential(
            nn.Linear(dim, dim),
            nn.ReLU(inplace=True),
            nn.BatchNorm1d(dim),
            nn.Dropout(0.2),  # 降低dropout率
            nn.Linear(dim, dim),
            nn.BatchNorm1d(dim)
        )
        self.act = nn.ReLU(inplace=True)

    def forward(self, x):
        return self.act(self.block(x) + x)


class ImprovedCrossAttention(nn.Module):
    """改进的跨注意力模块"""

    def __init__(self, dim=256, heads=8, num_layers=2):
        super().__init__()
        self.layers = nn.ModuleList([
            nn.MultiheadAttention(dim, heads, batch_first=True) for _ in range(num_layers)
        ])
        self.norms = nn.ModuleList([
            nn.LayerNorm(dim) for _ in range(num_layers)
        ])
        self.ffns = nn.ModuleList([
            nn.Sequential(
                nn.Linear(dim, dim * 4),
                nn.GELU(),
                nn.Linear(dim * 4, dim)
            ) for _ in range(num_layers)
        ])

    # 修改 ImprovedCrossAttention.forward 返回所有层注意力
    def forward(self, query, context):
        all_attn_weights = []  # 存储所有层注意力
        for attn, norm, ffn in zip(self.layers, self.norms, self.ffns):
            attn_out, attn_weights = attn(query, context, context)
            query = query + attn_out
            query = norm(query)
            ffn_out = ffn(query)
            query = query + ffn_out
            all_attn_weights.append(attn_weights)  # 收集每层注意力
        return query, all_attn_weights  # 返回所有层


# 教师模型
class TeacherModel(nn.Module):
    def __init__(self, struct_dim, mode='mode4', hbond_idx=None):
        super().__init__()

        # 图像特征提取
        base = resnet152(weights=ResNet152_Weights.IMAGENET1K_V1)
        feat_dim = base.fc.in_features
        base.fc = nn.Identity()
        self.backbone = base
        self.mode = mode

        # === mode4 的双图像编码器 ===
        if mode == 'mode4':
            def _resnet_conv():
                net = resnet152(weights=ResNet152_Weights.IMAGENET1K_V1)
                return nn.Sequential(*list(net.children())[:-2])  # (B,2048,H/32,W/32)

            self.enc_complex = _resnet_conv()
            self.enc_ligand = _resnet_conv()
            self.token_proj = nn.Linear(2048, 256)
            self.cross_attn = ImprovedCrossAttention(dim=256, heads=8, num_layers=2)

            # 交互后我们要拿到两张图的 pooled 表征各 256 维 → 512
            img_feat_dim = 512
            self.backbone = None


        else:
            self.backbone = base  # 其他模式使用 backbone
            img_feat_dim = feat_dim

        # 初始化结构缩放向量
        scale = None
        if struct_dim > 0:  # 有结构特征时才创建缩放向量
            if mode in ['mode2', 'mode3', 'mode4', 'mode5']:
                scale = torch.ones(struct_dim)
                if mode in ['mode3', 'mode4', 'mode5'] and hbond_idx is not None:
                    scale[hbond_idx] = 3.0  # mode3,4,5下氢键权重x3
            else:
                scale = torch.ones(struct_dim)

        # 注册缓冲区（统一在这里注册）
        if scale is not None:
            self.register_buffer('struct_scale', scale)
        else:
            self.register_buffer('struct_scale', torch.empty(0))

        # 结构编码器
        self.struct_encoder = None
        struct_out = 0
        if struct_dim > 0:
            hidden = 128
            if mode == 'mode1':  # mode1只有3个特征
                self.struct_encoder = nn.Sequential(
                    nn.Linear(struct_dim, hidden // 2),
                    nn.ReLU(inplace=True),
                    nn.BatchNorm1d(hidden // 2)
                )
                struct_out = hidden // 2
            else:  # mode2/mode3/mode4
                self.struct_encoder = nn.Sequential(
                    nn.Linear(struct_dim, hidden),
                    nn.ReLU(inplace=True),
                    nn.BatchNorm1d(hidden),
                    ResidualBlock(hidden),
                    nn.Linear(hidden, hidden // 2),
                    nn.ReLU(inplace=True)
                )
                struct_out = hidden // 2

        # ===== 添加日志输出 =====
        # 用于计数 forward 被调用的次数
        self._forward_count = 0
        # 日志间隔：每隔多少次 forward 输出一次 debug
        self._log_interval = 10
        logging.info(f"初始化 {mode} 模式模型: struct_dim={struct_dim}, struct_out={struct_out}")

        # === 回归头输入维度 ===

        combined = img_feat_dim + struct_out

        # 增加网络深度和宽度
        self.regressor = nn.Sequential(
            nn.Linear(combined, 128),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, 1)
        )
        # —— 新增：纯结构回归头 ——
        self.struct_regressor = nn.Sequential(
            nn.Linear(struct_out, 128),
            nn.ReLU(),
            nn.Linear(128, 1)
        )

        # 更精细的权重初始化
        for layer in self.regressor:
            if isinstance(layer, nn.Linear):
                nn.init.kaiming_normal_(layer.weight, mode='fan_in', nonlinearity='relu')
                nn.init.constant_(layer.bias, 0.0)
                # 添加权重归一化
                weight_norm(layer)

        # 梯度监控
        self.grad_norms = []

        if mode == 'mode5':
            # ✅ 加载 ResNet152 并移除分类头
            base = resnet152(weights=ResNet152_Weights.IMAGENET1K_V1)
            feat_dim = base.fc.in_features  # ResNet152 输出维度为 2048
            base.fc = nn.Identity()  # 去掉分类头，保留特征提取器
            self.backbone = base
            img_feat_dim = feat_dim

            # 结构编码器
            hidden = 128
            self.struct_encoder = nn.Sequential(
                nn.Linear(struct_dim, hidden),
                nn.ReLU(inplace=True),
                nn.BatchNorm1d(hidden),
                ResidualBlock(hidden),
                nn.Linear(hidden, hidden // 2),
                nn.ReLU(inplace=True)
            )
            struct_out = hidden // 2

            # Mid-Level Fusion 模块
            self.mid_fusion = nn.Sequential(
                nn.Linear(img_feat_dim + struct_out, 512),
                nn.ReLU(),
                nn.BatchNorm1d(512),
                nn.Dropout(0.3)
            )

            # 回归头
            self.regressor = nn.Sequential(
                nn.Linear(512, 128),
                nn.ReLU(),
                nn.Linear(128, 1)
            )

    def forward(self, img=None, struct=None, img_ligand=None, log_stats=False, return_feats=False, use_img=True, use_aa=True):
        # 梯度监控
        if self.training:  # 只在训练时检查
            for name, param in self.named_parameters():
                if param.grad is not None and torch.isnan(param.grad).any():
                    logging.warning(f"参数 {name} 梯度出现NaN前向传播前")
        self._forward_count += 1
        # 如果只给了 struct，就走纯指纹通道
        if img is None and img_ligand is None and struct is not None:
            return {
                "pred": self.forward_fp(struct),
                "ligand_rep": None,
                "pocket_rep": None,
                "attn_map": None
            }

        # 设备转移
        img = img.to(self.struct_scale.device)
        struct = struct.to(self.struct_scale.device)

        if self.mode == 'mode4':
            img_ligand = img_ligand.to(self.struct_scale.device)

            # --- 图像特征提取 ---
            def encode_tokens(encoder, img):
                feat = encoder(img)  # [B,2048,H',W']
                feat = feat.flatten(2).transpose(1, 2)  # [B,L,2048]
                return self.token_proj(feat)  # [B,L,256]

            # 复合物图像编码 (蛋白质口袋上下文)
            tokens_c = encode_tokens(self.enc_complex, img)  # [B,Lc,256]

            # 配体图像编码 (查询)
            tokens_l = encode_tokens(self.enc_ligand, img_ligand)  # [B,Lq,256]

            # 🌟 [新增] 图像掩码：如果关闭图像分支，直接把提出来的特征置零
            if not use_img:
                tokens_c = torch.zeros_like(tokens_c)
                tokens_l = torch.zeros_like(tokens_l)

            aligned, attn_weights = self.cross_attn(tokens_l, tokens_c)  
            vec_l = aligned.mean(dim=1)  
            vec_c = tokens_c.mean(dim=1) 

            # 🌟 [修改] 氨基酸属性掩码：如果关闭氨基酸，保留最后 1024 维(SMILES)，前面的置零
            if not use_aa:
                struct_masked = struct.clone()
                struct_masked[:, :-1024] = 0.0  # 把前面所有物理化学属性置零
                struct_feat = self.struct_encoder(struct_masked * self.struct_scale) 
            else:
                struct_feat = self.struct_encoder(struct * self.struct_scale) 

            feat = torch.cat([vec_c, vec_l, struct_feat], dim=1)


            if return_feats:
                return {
                    "pred": self.regressor(feat).squeeze(-1),
                    "ligand_rep": vec_l,  # 配体表示向量
                    "pocket_rep": vec_c,  # 口袋表示向量
                    "attn_maps": attn_weights,  # 所有层注意力图列表
                    "aligned_rep": aligned  # 对齐后的配体表示
                }
            else:
                return self.regressor(feat).squeeze(-1)

            # ========== mode5：mid-level fusion ==========
        elif self.mode == 'mode5':
            img_feat = self.backbone(img)  # [B, 2048]
            struct_feat = self.struct_encoder(struct * self.struct_scale)  # [B, Ds]
            fused = self.mid_fusion(torch.cat([img_feat, struct_feat], dim=1))
            return self.regressor(fused).squeeze(-1)

        # ========== baseline / mode1-4 ==========
        else:  # baseline, mode1-4
            img_feat = self.backbone(img)  # [B, 2048]
            if struct.size(1) > 0:
                struct_feat = self.struct_encoder(struct * self.struct_scale)
                img_feat = torch.cat([img_feat, struct_feat], dim=1)  # [B, 2048 + Ds]
            return self.regressor(img_feat).squeeze(-1)


# 数据质量检查
def check_data_quality(main_df, struct_df):
    logging.info("\n===== 数据质量检查 =====")
    logging.info(f"总样本数: {len(main_df)}")
    logging.info(f"亲和力统计: min={main_df['Affinity'].min():.4f}, max={main_df['Affinity'].max():.4f}, "
                 f"mean={main_df['Affinity'].mean():.4f}, std={main_df['Affinity'].std():.4f}")

    # 检查SMILES可用性
    if 'SMILES' in main_df.columns:
        valid_smiles = main_df['SMILES'].notna().sum()
        logging.info(f"有效SMILES数量: {valid_smiles}/{len(main_df)}")

    # 检查缺失值
    missing_main = main_df.isnull().sum().sum()
    missing_struct = struct_df.isnull().sum().sum()
    logging.info(f"主数据集缺失值数量: {missing_main}")
    logging.info(f"结构数据集缺失值数量: {missing_struct}")

    # 可视化亲和力分布
    plt.figure(figsize=(10, 6))
    sns.histplot(main_df['Affinity'], bins=30, kde=True)
    plt.title('Affinity Distribution')
    plt.savefig('affinity_distribution.png', dpi=600, bbox_inches='tight')
    plt.close()




# 训练流程
def train_teacher(mode='mode5', data_ratio=1.0, variant='Full'):
    torch.cuda.empty_cache()
    use_img = variant in ['Full', 'C']
    use_aa = variant in ['Full', 'B']
    # 加载数据
    try:
        main_df = pd.read_csv(DATA_CSV, encoding='utf-8')
    except UnicodeDecodeError:
        try:
            main_df = pd.read_csv(DATA_CSV, encoding='gbk')
        except UnicodeDecodeError:
            try:
                main_df = pd.read_csv(DATA_CSV, encoding='latin-1')
            except UnicodeDecodeError as e:
                logging.error(f"无法读取主数据CSV文件: {e}")
                raise

    try:
        struct_df = pd.read_csv(STRUCT_CSV, encoding='utf-8')
    except UnicodeDecodeError:
        try:
            struct_df = pd.read_csv(STRUCT_CSV, encoding='gbk')
        except UnicodeDecodeError:
            try:
                struct_df = pd.read_csv(STRUCT_CSV, encoding='latin-1')
            except UnicodeDecodeError as e:
                logging.error(f"无法读取结构数据CSV文件: {e}")
                raise

    # 数据清洗：确保 Filename 列是字符串且没有 NaN
    main_df['Filename'] = main_df['Filename'].astype(str)
    main_df = main_df[main_df['Filename'] != 'nan']

    struct_df['Filename'] = struct_df['Filename'].astype(str)
    struct_df = struct_df[struct_df['Filename'] != 'nan']
    
    if 0.0 < data_ratio < 1.0:
        # 1. 引入分层抽样工具
        from sklearn.model_selection import train_test_split
        
        # 2. 创建分层依据：将 Affinity 划分为 N 个等频区间（分位数）
        # 使用 pd.qcut 确保原始数据在每个区间内的样本量大致相等
        # duplicates='drop' 用于处理数据分布极不均匀导致分位数重合的情况
        n_bins = 10  # 建议根据总样本量调整，10-20个区间通常效果很好
        bins = pd.qcut(main_df['Affinity'], q=n_bins, labels=False, duplicates='drop')
        
        # 3. 执行分层抽样
        # train_size 设置为 data_ratio，利用 stratify 确保每个 bin 里的抽取比例一致
        main_df, _ = train_test_split(
            main_df,
            train_size=data_ratio,
            random_state=SEED,
            stratify=bins
        )
        
        main_df = main_df.reset_index(drop=True)
        logging.info(f"📊 分层数据量控制: 当前使用 {data_ratio * 100}% 的数据（分位数分层），样本量为 {len(main_df)}。")
        
    # 数据质量检查
    check_data_quality(main_df, struct_df)

    # 根据模式调整日志和保存路径
    TEACHER_SAVE = f'./teacher_model_{mode}_{variant}_ratio_{data_ratio}.pth'
    log_file = f'teacher_training_{mode}_{variant}.log'
    logging.getLogger().handlers.clear()  # 清除旧处理器
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(message)s',
        handlers=[logging.FileHandler(log_file, encoding='utf-8'), SafeLogHandler()]
    )

    # 模式特定日志
    logging.info(f"\n===== 消融实验模式: {mode.upper()} =====")
    if mode == 'baseline':
        logging.info("使用图像特征 + SMILES指纹")
    elif mode == 'mode1':
        logging.info("使用图像 + 氨基酸数目+ SMILES指纹")
    elif mode == 'mode2':
        logging.info("使用图像 + 完整结构特征+ SMILES指纹")
    elif mode == 'mode3':
        logging.info("使用完整结构特征 + 氢键权重x3+ SMILES指纹")
    elif mode == 'mode4':
        logging.info("使用双图像输入（复合物+配体）+ 跨图像注意力 + 结构特征")
    elif mode == 'mode5':
        logging.info("中层融合")

    # 替代方案：使用更智能的分箱策略
    def create_robust_bins(affinity_series, min_samples_per_bin=2):
        """创建健壮的分箱，确保每个分箱有足够样本"""
        n_samples = len(affinity_series)

        # 计算合适的箱数
        max_bins = min(10, n_samples // min_samples_per_bin)
        max_bins = max(2, max_bins)  # 至少2个分箱

        for n_bins in range(max_bins, 1, -1):
            bins = pd.cut(affinity_series, bins=n_bins, labels=False)
            bin_counts = bins.value_counts()

            if bin_counts.min() >= min_samples_per_bin:
                logging.info(f"使用 {n_bins} 个分箱，样本分布: {dict(bin_counts)}")
                return bins

        # 如果所有尝试都失败，使用分位数分箱
        logging.warning("使用分位数分箱作为备选方案")
        return pd.qcut(affinity_series, q=2, labels=False, duplicates='drop')

    # 在 train_teacher 函数中使用：
    main_df['affinity_bin'] = create_robust_bins(main_df['Affinity'], min_samples_per_bin=2)
    # 分层拆分：训练+验证 vs 测试
    sss = StratifiedShuffleSplit(n_splits=1, test_size=TEST_RATIO, random_state=SEED)
    for tr_val_idx, test_idx in sss.split(main_df, main_df['affinity_bin']):
        trval = main_df.iloc[tr_val_idx].reset_index(drop=True)
        test_df = main_df.iloc[test_idx].reset_index(drop=True)
    # 分层拆分：训练 vs 验证
    val_ratio_adj = VAL_RATIO / (1 - TEST_RATIO)
    sss_val = StratifiedShuffleSplit(n_splits=1, test_size=val_ratio_adj, random_state=SEED)
    for train_idx, val_idx in sss_val.split(trval, trval['affinity_bin']):
        train_df = trval.iloc[train_idx].reset_index(drop=True)
        val_df = trval.iloc[val_idx].reset_index(drop=True)
    # 删除临时 bin 列
    for df_ in (train_df, val_df, test_df):
        df_.drop(columns=['affinity_bin'], inplace=True)

    # 检查真实值范围
    logging.info("\n===== 标签范围检查 =====")
    logging.info(f"训练集真实值范围: {train_df['Affinity'].min():.4f} - {train_df['Affinity'].max():.4f}")
    logging.info(f"验证集真实值范围: {val_df['Affinity'].min():.4f} - {val_df['Affinity'].max():.4f}")
    logging.info(f"测试集真实值范围: {test_df['Affinity'].min():.4f} - {test_df['Affinity'].max():.4f}")

    # === 创建动态变换 ===
    base_transform = transforms.Compose([
        transforms.Resize((IMG_SIZE, IMG_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])

    # 仅为 mode4 训练集添加数据增强
    train_transform = base_transform
    if mode == 'mode4':
        train_transform = transforms.Compose([
            transforms.Resize((IMG_SIZE, IMG_SIZE)),
            transforms.RandomHorizontalFlip(p=0.5),
            transforms.RandomRotation(15),
            transforms.ColorJitter(brightness=0.2, contrast=0.2),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])

    # 创建数据集
    # === 创建数据集时传入变换 ===
    train_ds = TeacherDataset(
        train_df, struct_df,
        scale_label=True,
        mode=mode,
        transform=train_transform  # 传入动态变换
    )
    feature_scaler = train_ds.scalers['feature']
    label_scaler = train_ds.scalers['label']  # 获取标签缩放器

    logging.info("\n===== 特征标准化检查 =====")
    if hasattr(feature_scaler, 'mean_') and hasattr(feature_scaler, 'scale_'):
        logging.info(f"结构特征均值: {feature_scaler.mean_[:5]}... (共{len(feature_scaler.mean_)}维)")
        logging.info(f"结构特征标准差: {feature_scaler.scale_[:5]}... (共{len(feature_scaler.scale_)}维)")
    else:
        logging.warning("特征缩放器未拟合或不可用")

        # 验证/测试集使用基础变换（无增强）
    val_ds = TeacherDataset(
        val_df, struct_df,
        feature_scaler=feature_scaler,
        label_scaler=label_scaler,
        scale_label=True,
        mode=mode,
        transform=base_transform  # 始终用基础变换
    )
    test_ds = TeacherDataset(
        test_df, struct_df,
        feature_scaler=feature_scaler,
        label_scaler=label_scaler,
        scale_label=True,
        mode=mode,
        transform=base_transform  # 始终用基础变换
    )

    # 创建数据加载器
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=2, drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, num_workers=2)
    test_loader = DataLoader(test_ds, batch_size=BATCH_SIZE, num_workers=2)

    # 获取模型参数
    struct_dim = train_ds.struct_feats.shape[1]
    h_idx = None
    if mode in ['mode2', 'mode3', 'mode4', 'mode5']:
        feature_columns = struct_df.columns.tolist()[1:]
        try:
            h_idx = feature_columns.index('H')
            logging.info(f"氢键特征索引: {h_idx}")
        except ValueError:
            logging.warning("未找到氢键特征'H'，使用默认位置")
            h_idx = 20

    # 创建模型
    model = TeacherModel(struct_dim, mode=mode, hbond_idx=h_idx).to(DEVICE)
    # 检查模型初始化
    logging.info("\n===== 模型初始化检查 =====")
    if mode in ['mode2', 'mode3', 'mode4', 'mode5'] and hasattr(model, 'struct_scale'):
        logging.info(f"氢键特征缩放值: {model.struct_scale[h_idx]:.4f}")
    # 使用更稳定的优化配置
    optimizer = optim.Adam(model.parameters(), lr=1e-6, weight_decay=1e-5)  # 降低LR和权重衰减
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode='min', factor=0.5, patience=5, min_lr=1e-7
    )
    # 使用更稳定的Huber损失代替MSE
    criterion = nn.HuberLoss(delta=1.0)

    # 训练历史记录
    history = {
        'epoch': [], 'train_loss': [], 'val_loss': [], 'val_mae': [], 'val_r2': [], 'val_spearman': [], 'lr': []
    }

    # 早停相关变量
    best_val_loss = float('inf')
    best_val_mae = float('inf')
    best_val_r2 = -float('inf')
    best_composite_score = -float('inf')
    no_imp = 0
    best_model_state = None

    logging.info("\n===== 开始训练 =====")
    total_size = len(train_ds) + len(val_ds) + len(test_ds)
    logging.info(f"总体数据集大小: {total_size}")
    logging.info(f"训练集大小: {len(train_ds)}, 验证集大小: {len(val_ds)}, 测试集大小: {len(test_ds)}")
    logging.info(f"结构特征维度: {struct_dim}, H键索引: {h_idx}")
    logging.info(f"使用设备: {DEVICE}")
    logging.info(f"优化器: optim.Adam, 学习率: {LR}, 权重衰减: 1e-5")
    logging.info(f"损失函数: HuberLoss(delta=1.0)")

    for epoch in range(1, EPOCHS + 1):
        start_time = time.time()

        # 训练阶段
        model.train()
        train_losses = []
        nan_batches = 0  # 记录NaN批次数量

        for batch_idx, batch in enumerate(train_loader):
            if mode == 'mode4':
                img_comp, img_lig, struct, y = batch
                img_comp = img_comp.to(DEVICE)
                img_lig = img_lig.to(DEVICE)
                struct = struct.to(DEVICE)
                y = y.to(DEVICE)
                pred = model(img_comp, struct, img_ligand=img_lig, use_img=use_img, use_aa=use_aa)
            else:
                img, struct, y, _ = batch
                img = img.to(DEVICE)
                struct = struct.to(DEVICE)
                y = y.to(DEVICE)
                pred = model(img, struct)

            # 检查NaN值
            if torch.isnan(pred).any() or torch.isnan(y).any():
                nan_batches += 1
                logging.warning(f"批次 {batch_idx} 包含NaN值! 跳过该批次")
                optimizer.zero_grad()
                continue

            loss = criterion(pred, y)

            if torch.isnan(loss):
                nan_batches += 1
                logging.warning(f"批次 {batch_idx} 损失为NaN!")
                optimizer.zero_grad()
                continue

            # 反向传播
            loss.backward()

            # --- 梯度监控与裁剪 ---
            # 1. 检查NaN梯度
            nan_gradients = False
            for param in model.parameters():
                if param.grad is not None and torch.isnan(param.grad).any():
                    nan_gradients = True
                    break

            if nan_gradients:
                nan_batches += 1
                logging.warning(f"批次 {batch_idx} 梯度包含NaN! 跳过更新")
                optimizer.zero_grad()
                continue

            # 2. 计算梯度范数（使用PyTorch内置函数）
            total_norm = torch.nn.utils.clip_grad_norm_(
                model.parameters(),
                max_norm=MAX_GRAD_NORM,  # 应用梯度裁剪
                norm_type=2,
                error_if_nonfinite=True
            ).item()

            # 3. 记录梯度统计
            if hasattr(model, 'grad_norms'):
                model.grad_norms.append(total_norm)
            else:
                model.grad_norms = [total_norm]

            # 4. 定期记录梯度统计
            if (batch_idx + 1) % GRAD_NORM_LOG_INTERVAL == 0:
                if model.grad_norms:
                    avg_norm = sum(model.grad_norms) / len(model.grad_norms)
                    max_norm = max(model.grad_norms)
                    min_norm = min(model.grad_norms)
                    logging.info(
                        f"梯度统计: 批次 [{batch_idx + 1}/{len(train_loader)}] | "
                        f"平均范数: {avg_norm:.4f} | 最大: {max_norm:.4f} | 最小: {min_norm:.4f}"
                    )
                    model.grad_norms = []  # 重置记录

            # 5. 执行优化步骤
            optimizer.step()
            optimizer.zero_grad()

            train_losses.append(loss.item())
        # ===== 结束梯度监控 =====

        if nan_batches > 0:
            logging.warning(f"本epoch共有 {nan_batches} 个批次因NaN被跳过")

        if not train_losses:
            logging.error("本epoch所有批次损失均为NaN，终止训练")
            break

        train_loss = np.mean(train_losses)

        # 验证阶段
        model.eval()
        val_losses, val_preds, val_trues = [], [], []
        with torch.no_grad():
            for batch in val_loader:
                if mode == 'mode4':
                    img_comp, img_lig, struct, y = batch
                    img_comp = img_comp.to(DEVICE)
                    img_lig = img_lig.to(DEVICE)
                    struct = struct.to(DEVICE)
                    y = y.to(DEVICE)
                    pred_scaled = model(img_comp, struct, img_ligand=img_lig, use_img=use_img, use_aa=use_aa)
                else:
                    img, struct, y, _ = batch
                    img = img.to(DEVICE)
                    struct = struct.to(DEVICE)
                    y = y.to(DEVICE)
                    pred_scaled = model(img, struct)

                loss = criterion(pred_scaled, y)
                val_losses.append(loss.item())

                val_preds.append(pred_scaled.detach().cpu().numpy().reshape(-1, 1))
                val_trues.append(y.detach().cpu().numpy().reshape(-1, 1))

        val_loss = np.mean(val_losses)
        # 将列表中的 Tensor 拼接成一个大 Tensor，并转为 NumPy 数组
        val_preds = np.vstack(val_preds)  # 保持二维 [n, 1]
        val_trues = np.vstack(val_trues)  # 保持二维 [n, 1]
        # 反标准化
        val_preds = label_scaler.inverse_transform(val_preds).squeeze()
        val_trues = label_scaler.inverse_transform(val_trues).squeeze()

        # 调试输出
        logging.info(f"val_preds 统计: min={val_preds.min():.4f}, max={val_preds.max():.4f}, "
                     f"mean={val_preds.mean():.4f}, std={val_preds.std():.4f}")
        logging.info(f"val_trues 统计: min={val_trues.min():.4f}, max={val_trues.max():.4f}, "
                     f"mean={val_trues.mean():.4f}, std={val_trues.std():.4f}")

        # 计算验证集指标
        val_mae = mean_absolute_error(val_trues, val_preds)
        val_r2 = r2_score(val_trues, val_preds)
        val_pearson = pearsonr(val_trues, val_preds)[0] if np.std(val_preds) > 1e-8 and np.std(
            val_trues) > 1e-8 else 0.0
        try:
            val_spearman = spearmanr(val_trues, val_preds)[0]
        except ValueError:
            val_spearman = 0.0
            logging.warning("计算Spearman时发生错误，设为0.0")

        # 更新调度器
        scheduler.step(val_mae)
        current_lr = optimizer.param_groups[0]['lr']

        # 记录历史
        history['epoch'].append(epoch)
        history['train_loss'].append(train_loss)
        history['val_loss'].append(val_loss)
        history['val_mae'].append(val_mae)
        history['val_r2'].append(val_r2)
        history['val_spearman'].append(val_spearman)
        history['lr'].append(current_lr)

        # 记录学习率变化
        if epoch > 1 and current_lr < history['lr'][-2]:
            logging.info(f"学习率降低: {history['lr'][-2]:.2e} -> {current_lr:.2e}")

        # 记录日志
        epoch_time = time.time() - start_time
        logging.info(f"Epoch {epoch}/{EPOCHS} | Time: {epoch_time:.1f}s | LR: {current_lr:.2e}")
        logging.info(f"Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f}")
        logging.info(
            f"Val MAE: {val_mae:.4f} | Val R²: {val_r2:.4f} | Val Pearson: {val_pearson:.4f} | Val Spearman: {val_spearman:.4f}")

        # 计算综合评分
        composite_score = (0.4 * (1 / (val_mae + 1e-8))) + (0.6 * val_r2)

        # 早停判断
        if composite_score > best_composite_score:
            improvement = True
        else:
            improvement = False

        if improvement:
            no_imp = 0
            best_val_mae = val_mae
            best_val_r2 = val_r2
            best_composite_score = composite_score
            best_model_state = model.state_dict().copy()
            torch.save(model.state_dict(), TEACHER_SAVE)
            logging.info(f"模型改进! 综合评分: {composite_score:.4f} | "
                         f"Val Loss={val_loss:.4f}, MAE={val_mae:.4f}, R²={val_r2:.4f}")
        else:
            no_imp += 1
            if no_imp >= PATIENCE:
                logging.info(f"早停触发, 最佳综合评分: {best_composite_score:.4f} | "
                             f"最佳MAE: {best_val_mae:.4f}, 最佳R²: {best_val_r2:.4f}")
                break

    # 训练结束
    logging.info("\n===== 训练完成 =====")

    # 加载最佳模型
    if best_model_state is not None:
        model.load_state_dict(best_model_state)
    else:
        model.load_state_dict(torch.load(TEACHER_SAVE))
    model.eval()

    # 验证集评估
    val_losses, val_preds, val_trues = [], [], []
    with torch.no_grad():
        for batch in val_loader:
            if mode == 'mode4':
                img_comp, img_lig, struct, y = batch
                img_comp = img_comp.to(DEVICE)
                img_lig = img_lig.to(DEVICE)
                struct = struct.to(DEVICE)
                y = y.to(DEVICE)
                pred = model(img_comp, struct, img_ligand=img_lig, use_img=use_img, use_aa=use_aa)
            else:
                img, struct, y, _ = batch
                img = img.to(DEVICE)
                struct = struct.to(DEVICE)
                y = y.to(DEVICE)
                pred = model(img, struct)

            loss = criterion(pred, y)
            val_losses.append(loss.item())
            val_preds.append(pred.detach().cpu().numpy().reshape(-1, 1))  # 使用pred
            val_trues.append(y.detach().cpu().numpy().reshape(-1, 1))

            val_loss = np.mean(val_losses)
    # 将列表中的 Tensor 拼接成一个大 Tensor，并转为 NumPy 数组
    val_preds = np.vstack(val_preds)
    val_trues = np.vstack(val_trues)
    # 反标准化
    val_preds = label_scaler.inverse_transform(val_preds).squeeze()
    val_trues = label_scaler.inverse_transform(val_trues).squeeze()

    # 测试集评估
    test_preds, test_trues = [], []
    with torch.no_grad():
        for batch in test_loader:
            if mode == 'mode4':
                img_comp, img_lig, struct, y = batch
                img_comp = img_comp.to(DEVICE)
                img_lig = img_lig.to(DEVICE)
                struct = struct.to(DEVICE)
                y = y.to(DEVICE)
                pred = model(img_comp, struct, img_ligand=img_lig, use_img=use_img, use_aa=use_aa)
            else:
                img, struct, y, _ = batch
                img = img.to(DEVICE)
                struct = struct.to(DEVICE)
                y = y.to(DEVICE)
                pred = model(img, struct)

            # 收集标准化后的值
            test_preds.append(pred.detach().cpu().numpy().reshape(-1, 1))
            test_trues.append(y.detach().cpu().numpy().reshape(-1, 1))

    # 转换为NumPy数组
    test_preds = np.vstack(test_preds)
    test_trues = np.vstack(test_trues)

    # 使用训练集的scaler进行反标准化
    test_preds = label_scaler.inverse_transform(test_preds).squeeze()
    test_trues = label_scaler.inverse_transform(test_trues).squeeze()

    # 计算关键指标
    def calc_metrics(true, pred):
        # 确保输入是一维数组
        true = np.asarray(true).flatten()
        pred = np.asarray(pred).flatten()

        # 检查数据有效性
        if len(true) < 2 or np.std(pred) < 1e-8 or np.std(true) < 1e-8:
            logging.warning("无效数据计算指标: 长度={}, pred_std={:.4f}, true_std={:.4f}".format(
                len(true), np.std(pred), np.std(true)))
            return {'MAE': 0, 'RMSE': 0, 'R2': 0, 'Pearson': 0, 'Spearman': 0, 'Std': 0}
        try:
            spearman_val = spearmanr(true, pred)[0]
        except ValueError:
            spearman_val = 0.0

        return {
            'MAE': mean_absolute_error(true, pred),
            'RMSE': np.sqrt(mean_squared_error(true, pred)),
            'R2': r2_score(true, pred),
            'Pearson': pearsonr(true, pred)[0],
            'Spearman': spearman_val,
            'Std': np.std(true - pred)
        }



    # 计算验证集指标（使用已反标准化的数据）
    val_metrics = calc_metrics(val_trues, val_preds)
    test_metrics = calc_metrics(test_trues, test_preds)


    # 1. 导出“结合能分布区间”对精度影响的数据 (解除对 mode 的限制，使所有模式都能输出分布报告)
    try:
        test_df_analysis = pd.DataFrame({'True': test_trues, 'Pred': test_preds})
        # 按照真实结合能等频划分为 5 个区间
        test_df_analysis['Affinity_Bin'] = pd.qcut(test_df_analysis['True'], q=5, precision=2)
        
        bin_metrics = []
        for bin_name, group in test_df_analysis.groupby('Affinity_Bin', observed=True):
            if len(group) > 0:
                b_mae = mean_absolute_error(group['True'], group['Pred'])
                b_rmse = np.sqrt(mean_squared_error(group['True'], group['Pred']))
                b_r2 = r2_score(group['True'], group['Pred'])
                b_spearman = spearmanr(group['True'], group['Pred'])[0] if len(group) > 1 else 0.0
                bin_metrics.append({
                    'Bin_Range': str(bin_name),
                    'Count': len(group),
                    'MAE': b_mae,
                    'RMSE': b_rmse,
                    'R2': b_r2,           # 新增 R2
                    'Spearman': b_spearman
                })
        
        bin_metrics_df = pd.DataFrame(bin_metrics)
        # 每次运行都会覆盖，最终会保留数据量为 1.0 (最佳模型) 时的区间分布报告
        bin_metrics_df.to_csv(f'affinity_distribution_impact_{mode}.csv', index=False)
        logging.info(f"已导出亲和力分布区间误差数据至: affinity_distribution_impact_{mode}.csv")
    except Exception as e:
        logging.warning(f"分布误差分析计算失败: {e}")

    # 2. 追加导出“数据量”对精度影响的数据
    volume_log_file = 'data_volume_impact.csv'
    volume_data = {
        'Mode': mode,
        'Data_Ratio': data_ratio,
        'Train_Size': len(train_ds),
        'MAE': test_metrics['MAE'],
        'RMSE': test_metrics['RMSE'],
        'R2': test_metrics['R2'],
        'Spearman': test_metrics['Spearman']
    }
    volume_df = pd.DataFrame([volume_data])
    # 追加写入，以便多次运行不同 ratio 后形成完整数据表
    if os.path.exists(volume_log_file):
        volume_df.to_csv(volume_log_file, mode='a', header=False, index=False)
    else:
        volume_df.to_csv(volume_log_file, index=False)
    logging.info(f"已记录当前数据量 ({data_ratio*100}%) 的性能至: {volume_log_file}")



    # 检查预测分布
    plt.figure(figsize=(10, 5))
    plt.subplot(1, 2, 1)
    sns.histplot(val_trues, bins=30, color='blue', label='True', alpha=0.5)
    plt.title('True Values Distribution')
    plt.subplot(1, 2, 2)
    sns.histplot(val_preds, bins=30, color='red', label='Pred', alpha=0.5)
    plt.title('Predicted Values Distribution')
    plt.tight_layout()
    plt.savefig('val_distribution_check.png', dpi=300)
    plt.close()

    logging.info("\n===== 最终性能评估 =====")
    logging.info(f"验证集性能: MAE={val_metrics['MAE']:.4f}, RMSE={val_metrics['RMSE']:.4f}, "
                 f"R²={val_metrics['R2']:.4f}, Pearson={val_metrics['Pearson']:.4f}, "
                 f"Spearman={val_metrics['Spearman']:.4f}")

    logging.info(f"测试集性能: MAE={test_metrics['MAE']:.4f}, RMSE={test_metrics['RMSE']:.4f}, "
                 f"R²={test_metrics['R2']:.4f}, Pearson={test_metrics['Pearson']:.4f}, "
                 f"Spearman={test_metrics['Spearman']:.4f}")

    # 保存预测结果
    pd.DataFrame({'true': val_trues, 'pred': val_preds}).to_csv('val_predictions.csv', index=False)
    pd.DataFrame({'true': test_trues, 'pred': test_preds}).to_csv('test_predictions.csv', index=False)

    # 保存训练历史
    hist_df = pd.DataFrame(history)
    hist_df.to_csv('teacher_training_history.csv', index=False)

    import joblib
    joblib.dump(label_scaler, f"label_scaler_ratio_{data_ratio}.pkl")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=MODES, default='mode4',
                        help='消融实验模式: baseline, mode1, mode2, mode3, mode4, mode5')
    parser.add_argument('--data_ratio', type=float, default=1.0,
                        help='单次运行时使用的数据比例')
    
    # 新增：一键自动化实验触发器
    parser.add_argument('--auto_experiment', action='store_true',
                        help='一键跑完所有数据量 (0.2, 0.4, 0.6, 0.8, 1.0) 并生成完整折线图数据')
    parser.add_argument('--variant', choices=['Full', 'A', 'B', 'C'], default='Full',
                        help='消融实验变体: Full(全开), A(仅SMILES), B(无图像), C(无氨基酸)')
    
    args = parser.parse_args()
    
    if args.auto_experiment:
        logging.info("🚀 开启全自动实验模式：将连续测试不同数据量对模型性能的影响")
        # 定义你要测试的数据量梯度
        ratios = [0.2, 0.4, 0.6, 0.8, 1.0]
        volume_log_file = 'data_volume_impact.csv'
        
        # 运行前必须清理旧的合并记录，防止多次运行导致图表折线混乱
        if os.path.exists(volume_log_file):
            os.remove(volume_log_file)
            logging.info(f"已清理历史记录文件: {volume_log_file}")
            
        for ratio in ratios:
            logging.info("\n" + "="*60)
            logging.info(f"正在进行自动化实验: 投入 {ratio*100}% 的训练数据")
            logging.info("="*60)
            train_teacher(mode=args.mode, data_ratio=ratio)
            
        logging.info("\n所有数据量维度的实验已运行完毕！")
        logging.info("请运行 `python visualize_results.py` 生成一区 SCI 级别图表。")
    else:
        train_teacher(mode=args.mode, data_ratio=args.data_ratio, variant=args.variant)

