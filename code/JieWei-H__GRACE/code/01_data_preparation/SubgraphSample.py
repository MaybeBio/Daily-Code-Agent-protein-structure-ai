import random
from torch.utils.data import Dataset, DataLoader
import torch.multiprocessing as mp

class SubgraphSampler:
    """子图采样器"""
    def __init__(self, adj_sparse, node_id_to_idx, num_nodes, subgraph_size=1000):
        self.adj_sparse = adj_sparse
        self.node_id_to_idx = node_id_to_idx
        self.num_nodes = num_nodes
        self.subgraph_size = subgraph_size
        self.all_nodes = list(range(num_nodes))
        
    def sample_subgraph(self, center_nodes=None):
        """采样一个子图"""
        if center_nodes is None:
            # 随机选择中心节点
            center_nodes = random.sample(self.all_nodes, min(10, self.num_nodes))
        
        # 使用BFS采样邻居节点
        sampled_nodes = set(center_nodes)
        queue = list(center_nodes)
        
        while queue and len(sampled_nodes) < self.subgraph_size:
            node = queue.pop(0)
            # 获取邻居
            neighbors = self.adj_sparse[node].indices
            for neighbor in neighbors:
                if neighbor not in sampled_nodes and len(sampled_nodes) < self.subgraph_size:
                    sampled_nodes.add(neighbor)
                    queue.append(neighbor)
        
        sampled_nodes = list(sampled_nodes)
        
        # 构建子图邻接矩阵
        node_mapping = {old_idx: new_idx for new_idx, old_idx in enumerate(sampled_nodes)}
        subgraph_adj = np.zeros((len(sampled_nodes), len(sampled_nodes)))
        
        for i, node_i in enumerate(sampled_nodes):
            neighbors = self.adj_sparse[node_i].indices
            for neighbor in neighbors:
                if neighbor in node_mapping:
                    j = node_mapping[neighbor]
                    subgraph_adj[i, j] = 1
        
        return sampled_nodes, torch.FloatTensor(subgraph_adj)

class PPISubgraphDataset(Dataset):
    """PPI子图数据集"""
    def __init__(self, ppi_pairs, node_id_to_idx, adj_sparse, num_nodes, 
                 negative_ratio=1.0, subgraph_size=1000):
        self.ppi_pairs = ppi_pairs
        self.node_id_to_idx = node_id_to_idx
        self.adj_sparse = adj_sparse
        self.num_nodes = num_nodes
        self.negative_ratio = negative_ratio
        self.subgraph_size = subgraph_size
        self.sampler = SubgraphSampler(adj_sparse, node_id_to_idx, num_nodes, subgraph_size)
        
        # 生成负样本
        self._generate_negative_samples()
        
    def _generate_negative_samples(self):
        """生成负样本"""
        self.all_samples = []
        
        # 添加正样本
        for node1, node2 in self.ppi_pairs:
            if node1 in self.node_id_to_idx and node2 in self.node_id_to_idx:
                idx1 = self.node_id_to_idx[node1]
                idx2 = self.node_id_to_idx[node2]
                self.all_samples.append((idx1, idx2, 1))  # 1表示正样本
        
        # 添加负样本
        num_negatives = int(len(self.all_samples) * self.negative_ratio)
        for _ in range(num_negatives):
            # 随机选择两个不相连的节点
            while True:
                node1 = random.randint(0, self.num_nodes - 1)
                node2 = random.randint(0, self.num_nodes - 1)
                if node1 != node2 and self.adj_sparse[node1, node2] == 0:
                    self.all_samples.append((node1, node2, 0))  # 0表示负样本
                    break
    
    def __len__(self):
        return len(self.all_samples)
    
    def __getitem__(self, idx):
        node1, node2, label = self.all_samples[idx]
        
        # 采样包含这两个节点的子图
        center_nodes = [node1, node2]
        sampled_nodes, subgraph_adj = self.sampler.sample_subgraph(center_nodes)
        
        # 找到节点在子图中的新索引
        node_mapping = {old_idx: new_idx for new_idx, old_idx in enumerate(sampled_nodes)}
        node1_sub = node_mapping[node1]
        node2_sub = node_mapping[node2]
        
        return {
            'sampled_nodes': sampled_nodes,
            'subgraph_adj': subgraph_adj,
            'node1': node1_sub,
            'node2': node2_sub,
            'label': label
        }

def collate_fn(batch):
    """自定义批处理函数"""
    # 由于每个子图大小不同，我们需要分别处理每个样本
    return batch
  
