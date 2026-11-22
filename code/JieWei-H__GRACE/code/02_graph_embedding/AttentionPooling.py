import torch
import torch.nn as nn
import os
from pathlib import Path
from typing import Literal, Optional, Union
from tqdm import tqdm
import gc

class SelfAttentionPooling(nn.Module):
    """可配置的自注意力池化层"""
    def __init__(self, 
                 input_dim: int = 1280, 
                 hidden_ratio: float = 0.25,
                 activation: str = 'tanh'):
        """
        Args:
            input_dim: 输入特征维度
            hidden_ratio: 隐藏层维度比例 (default: 0.25)
            activation: 激活函数 'tanh' 或 'relu'
        """
        super().__init__()
        hidden_dim = int(input_dim * hidden_ratio)
        
        # 可配置的激活函数
        if activation.lower() == 'tanh':
            act_layer = nn.Tanh()
        elif activation.lower() == 'relu':
            act_layer = nn.ReLU()
        else:
            raise ValueError(f"不支持的激活函数: {activation}")
        
        self.attention = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            act_layer,
            nn.Linear(hidden_dim, 1),
            nn.Softmax(dim=1))
    
    def forward(self, x):
        weights = self.attention(x)
        return torch.sum(x * weights, dim=1)

def process_esm2_directory(
    directory_path: str,
    pooling_method: Literal['attention', 'mean', 'max'] = 'attention',
    attention_params: Optional[dict] = None,
    load_weights: Optional[str] = None,
    device: Union[str, torch.device] = "cuda:0" if torch.cuda.is_available() else "cpu"
) -> torch.Tensor:
    """
    处理ESM-2目录中的所有.pt文件（支持GPU加速）
    
    Args:
        directory_path: 包含.pt文件的目录路径
        pooling_method: 池化方法 ('attention', 'mean', 'max')
        attention_params: 自注意力池化的参数字典
        load_weights: 预训练权重文件路径 (.pth)
        device: 计算设备 ('cuda', 'cpu' 或 torch.device对象)
    
    Returns:
        形状为 (n_files, 1280) 的张量
    """
    # 设置设备
    device = torch.device(device)
    print(f"使用设备: {device}")
    
    pt_files = list(Path(directory_path).glob("*.pt"))
    if not pt_files:
        raise ValueError(f"目录中没有找到.pt文件: {directory_path}")
    
    # 初始化池化层并移动到设备
    if pooling_method == 'attention':
        params = attention_params or {}
        pooler = SelfAttentionPooling(input_dim=1280, **params).to(device)
        
        # 加载预训练权重
        if load_weights and os.path.exists(load_weights):
            # 确保权重加载到正确设备
            state_dict = torch.load(load_weights, map_location=device)
            pooler.load_state_dict(state_dict)
            print(f"加载预训练权重: {load_weights}")
        
        # 设置为评估模式
        pooler.eval()
    else:
        pooler = None
  
    
    #pooled_features = []
    pooled_features = torch.zeros(len(pt_files), 1280, dtype=torch.float32, device=device)
    print(f"开始处理 {len(pt_files)} 个文件 | 池化方法: {pooling_method}")
    
    for i, file_path in enumerate(tqdm(pt_files)):
        # print(file_path)
        # 加载数据并移动到设备
        tensor = torch.load(file_path, map_location=device)  # (L, 1280)
        
        if tensor.dim() != 2 or tensor.shape[1] != 1280:
            raise RuntimeError(f"文件 {file_path.name} 形状无效: {tensor.shape}")
        
        # 应用池化
        if pooling_method == 'attention':
            # 添加批次维度并计算
            pooled = pooler(tensor.unsqueeze(0)).squeeze(0)  # (1280,)
        elif pooling_method == 'mean':
            pooled = torch.mean(tensor, dim=0)  # (1280,)
        elif pooling_method == 'max':
            pooled = torch.max(tensor, dim=0).values  # (1280,)
        else:
            raise ValueError(f"未知池化方法: {pooling_method}")
        
        #pooled_features.append(pooled)
        pooled_features[i] = pooled.detach().cpu().clone()
        
        del tensor, pooled
        
    # print(f"已处理 {i+1}/{len(pt_files)} 文件 | 当前GPU内存: {get_gpu_memory()}")
    
    # 将所有结果堆叠在CPU上
    return pooled_features


def get_gpu_memory() -> str:
    """获取当前GPU内存使用情况"""
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1024**3
        reserved = torch.cuda.memory_reserved() / 1024**3
        return f"{allocated:.2f}GB / {reserved:.2f}GB"
    return "N/A"

