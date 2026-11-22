import torch
from torch.utils.data import Dataset, DataLoader
import random
import numpy as np
from collections import defaultdict
import math

class PPIDataset(Dataset):
    def __init__(self, ppi_pairs, node_id_to_idx, num_neg_samples=1):
        """
        PPI数据集类
        
        参数:
            ppi_pairs: PPI对列表 [(node1, node2), ...]
            node_id_to_idx: 节点ID到索引的映射
            num_neg_samples: 每个正样本对应的负样本数量
        """
        self.ppi_pairs = ppi_pairs
        self.node_id_to_idx = node_id_to_idx
        self.num_neg_samples = num_neg_samples
        self.node_ids = list(node_id_to_idx.keys())
        
        # 创建节点到邻居的映射，用于负采样
        self.node_neighbors = defaultdict(set)
        for node1, node2 in ppi_pairs:
            if node1 in node_id_to_idx and node2 in node_id_to_idx:
                idx1 = node_id_to_idx[node1]
                idx2 = node_id_to_idx[node2]
                self.node_neighbors[node1].add(node2)
                self.node_neighbors[node2].add(node1)
    
    def __len__(self):
        return len(self.ppi_pairs) * (1 + self.num_neg_samples)
    
    def __getitem__(self, idx):
        # 确定是正样本还是负样本
        is_positive = idx % (1 + self.num_neg_samples) == 0
        pair_idx = idx // (1 + self.num_neg_samples)
        
        if is_positive:
            # 正样本
            node1, node2 = self.ppi_pairs[pair_idx]
            label = 1
        else:
            # 负样本 - 采样不存在的边
            node1, node2 = self._sample_negative_pair()
            label = 0
        
        return {
            'node1': node1,
            'node2': node2,
            'label': label
        }
    
    def _sample_negative_pair(self):
        """采样不存在的PPI对"""
        while True:
            node1 = random.choice(self.node_ids)
            node2 = random.choice(self.node_ids)
            
            # 确保不是自环且不是已有的边
            if (node1 != node2 and 
                node2 not in self.node_neighbors[node1] and
                node1 not in self.node_neighbors[node2]):
                return node1, node2
    
    def _get_label_and_mask(self, node_id, label_dict, num_classes):
        """获取节点的标签和掩码"""
        if node_id in label_dict:
            return label_dict[node_id], 1.0  # 有标签，掩码为1
        else:
            return torch.zeros(num_classes), 0.0  # 无标签，返回全零向量，掩码为0

class PPIDataLoader:
    def __init__(self, dataset, batch_size, shuffle=True):
        self.dataset = dataset
        self.batch_size = batch_size
        self.shuffle = shuffle
        self.node_visited = set()  # 用于跟踪访问过的节点
    
    def __len__(self):
        """
        返回数据加载器中的批次数。
        对于图数据集，通常基于数据集大小和批次大小计算。
        使用向上取整以确保包含所有数据。
        """
        return math.ceil(len(self.dataset) / self.batch_size)
        
    def __iter__(self):
        # 创建数据加载器
        data_loader = DataLoader(
            self.dataset, 
            batch_size=self.batch_size, 
            shuffle=self.shuffle,
            collate_fn=self.collate_fn
        )
        
        for batch in data_loader:
            # 更新访问过的节点
            self.node_visited.update(batch['nodes_in_batch'])
            yield batch
    
    def collate_fn(self, batch):
        """整理批次数据"""
        # 收集批次中所有唯一的节点
        nodes_in_batch = set()
        for item in batch:
            nodes_in_batch.add(item['node1'])
            nodes_in_batch.add(item['node2'])
        
        # 转换为索引
        node_indices = [self.dataset.node_id_to_idx[node] for node in nodes_in_batch]
        
        # 收集标签和掩码
        labels = [item['label'] for item in batch]
        
        return {
            'node_pairs': [(item['node1'], item['node2']) for item in batch],
            'labels': torch.tensor(labels, dtype=torch.float32),
            'nodes_in_batch': list(nodes_in_batch),
            'node_indices': node_indices
        }
    
    def get_covered_nodes(self):
        """获取到目前为止覆盖的所有节点"""
        return self.node_visited
