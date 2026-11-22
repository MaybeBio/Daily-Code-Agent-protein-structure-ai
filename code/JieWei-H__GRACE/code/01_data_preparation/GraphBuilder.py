import torch
from pathlib import Path
import numpy as np
import random
import torch
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple

class PPIGraphBuilder:
    def __init__(self, node_dir: str, ppi_file: str):
        """
        蛋白质相互作用图构建器
        
        参数:
            node_dir: 存储节点特征文件(.pt)的目录路径
            ppi_file: 存储PPI对的CSV文件路径
        """
        self.node_dir = Path(node_dir)
        self.ppi_file = ppi_file
        self.node_id_to_idx: Dict[str, int] = {}
        self.sequences: List[torch.Tensor] = []
        self.adj: torch.Tensor = None
        
        # 初始化时加载所有数据
        self._load_node_features()
        self._load_ppi_pairs()
        self._build_adjacency_matrix()
        self._train_ppi()
    
    def _load_node_features(self) -> None:
        """加载所有节点特征并创建ID到索引的映射"""
        node_files = list(self.node_dir.glob("*.pt"))
        
        for idx, file_path in enumerate(node_files):
            node_id = file_path.stem  # 文件名作为节点ID
            self.node_id_to_idx[node_id] = idx
        
        # 加载所有节点特征序列
        self.sequences = [torch.load(file_path) for file_path in node_files]
    
    def _load_ppi_pairs(self) -> None:
        """从CSV文件加载PPI对"""
        data = pd.read_csv(self.ppi_file)
        self.ppi_pairs = [
            (row['protein1'], row['protein2']) 
            for _, row in data.iterrows()
        ]
        self.ppi_label = [
            (row['type']) 
            for _, row in data.iterrows()
        ]
    
    def _build_adjacency_matrix(self) -> None:
        """构建邻接矩阵（无向图）并添加自环"""
        num_nodes = len(self.sequences)
        self.adj = torch.zeros((num_nodes, num_nodes), dtype=torch.float32)
        
        # 填充邻接矩阵
        for node1, node2 in self.ppi_pairs:
            if node1 in self.node_id_to_idx and node2 in self.node_id_to_idx:
                idx1 = self.node_id_to_idx[node1]
                idx2 = self.node_id_to_idx[node2]
                self.adj[idx1, idx2] = 1.0
                self.adj[idx2, idx1] = 1.0  # 无向图对称
        
        # 添加自环
        self._add_self_loops()
        
    def _train_ppi(self) -> None:
        """创建训练用的PPI对：包含所有complex类型和部分normal类型（比例1:2）"""
        # 分离complex和normal类型的PPI对
        complex_pairs = []
        normal_pairs = []
        
        for i, label in enumerate(self.ppi_label):
            if label == 'complex':
                complex_pairs.append(self.ppi_pairs[i])
            elif label == 'normal':
                normal_pairs.append(self.ppi_pairs[i])
        
        # 确保有足够的complex和normal对
        if not complex_pairs:
            raise ValueError("No complex PPI pairs found in the dataset")
        if not normal_pairs:
            raise ValueError("No normal PPI pairs found in the dataset")
        
        # 计算需要采样的normal PPI数量 (complex数量的2倍)
        num_complex = len(complex_pairs)
        num_normal_to_sample = min(2 * num_complex, len(normal_pairs))
        
        # 随机采样normal PPI对
        sampled_normal_pairs = random.sample(normal_pairs, num_normal_to_sample)
        
        # 创建训练集
        self.train_pairs = complex_pairs + sampled_normal_pairs
        self.train_labels = [1] * len(complex_pairs) + [0] * len(sampled_normal_pairs)
        
        # 保存剩余normal PPI对用于按需采样
        self.remaining_normal = [pair for pair in normal_pairs if pair not in sampled_normal_pairs]
    
    def sample_validation_set(self, size: int = 20000) -> Tuple[List[Tuple[str, str]], List[int]]:
        """
        按需采样验证集
        
        参数:
            size: 验证集大小
            
        返回:
            验证集PPI对和标签
        """
        if size <= 0:
            return [], []
            
        # 确保请求的大小不超过可用数量
        actual_size = min(size, len(self.remaining_normal))
        
        if actual_size < size:
            print(f"警告: 请求的验证集大小({size})大于可用的normal PPI数量({len(self.remaining_normal)}), 使用{actual_size}个样本")
        
        # 随机采样验证集
        val_pairs = random.sample(self.remaining_normal, actual_size)
        val_labels = [0] * actual_size
        
        return val_pairs, val_labels
    
    def _add_self_loops(self) -> None:
        """为邻接矩阵添加自环（对角线设为1）"""
        for i in range(self.adj.size(0)):
            self.adj[i, i] = 1.0
    
    @property
    def node_features(self) -> torch.Tensor:
        """返回所有节点特征（堆叠为单个张量）"""
        return self.sequences
    
    @property
    def num_nodes(self) -> int:
        """返回节点数量"""
        return len(self.sequences)
    
    def get_node_index(self, node_id: str) -> int:
        """获取节点ID对应的索引"""
        return self.node_id_to_idx.get(node_id, -1)
    
    def get_node_id(self, index: int) -> str:
        """获取索引对应的节点ID"""
        reverse_map = {v: k for k, v in self.node_id_to_idx.items()}
        return reverse_map.get(index, "Unknown")
