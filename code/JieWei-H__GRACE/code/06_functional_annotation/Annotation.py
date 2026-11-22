import torch
import torch.nn as nn
import torch.nn.functional as F
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Union


class AnnotationDataLoader:
    """注释数据加载器"""
    
    def __init__(self, annotation_file: str, device: torch.device = None):
        """
        初始化注释数据加载器
        
        参数:
            annotation_file: 注释CSV文件路径
            device: 计算设备 (cuda/cpu)
        """
        self.annotation_file = Path(annotation_file)
        self.gene_names = []
        self.annotation_names = []
        self.annotation_matrix = None
        self.device = device if device else torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
    def load_annotations(self) -> torch.Tensor:
        """
        加载注释数据并转换为PyTorch张量
        
        返回:
            注释矩阵，形状为 [基因数, 注释数]
        """
        if not self.annotation_file.exists():
            raise FileNotFoundError(f"注释文件不存在: {self.annotation_file}")
            
        # 读取CSV文件
        df = pd.read_csv(self.annotation_file, index_col=0)
        
        # 提取基因名和注释名
        self.gene_names = df.index.tolist()
        self.annotation_names = df.columns.tolist()
        
        # 转换为numpy数组，然后转为PyTorch张量
        annotations = df.values.astype(np.float32)
        self.annotation_matrix = torch.tensor(annotations, device=self.device)
        
        print(f"加载注释数据: {len(self.gene_names)} 个基因, {len(self.annotation_names)} 个注释")
        print(f"数据设备: {self.annotation_matrix.device}")
        return self.annotation_matrix
    
    def get_gene_index(self, gene_name: str) -> int:
        """获取基因名对应的索引"""
        return self.gene_names.index(gene_name) if gene_name in self.gene_names else -1
    
    def get_gene_name(self, index: int) -> str:
        """获取索引对应的基因名"""
        return self.gene_names[index] if 0 <= index < len(self.gene_names) else "Unknown"
    
    def get_annotation_index(self, annotation_name: str) -> int:
        """获取注释名对应的索引"""
        return self.annotation_names.index(annotation_name) if annotation_name in self.annotation_names else -1

# 使用更深的网络和正则化
class ImprovedAutoencoder(nn.Module):
    def __init__(self, input_dim, hidden_dims=[128, 64], latent_dim=32, dropout=0.2):
        super().__init__()
        # 编码器
        encoder_layers = []
        prev_dim = input_dim
        for hidden_dim in hidden_dims:
            encoder_layers.extend([
                nn.Linear(prev_dim, hidden_dim),
                nn.BatchNorm1d(hidden_dim),
                nn.ReLU(),
                nn.Dropout(dropout)
            ])
            prev_dim = hidden_dim
        encoder_layers.append(nn.Linear(prev_dim, latent_dim))
        self.encoder = nn.Sequential(*encoder_layers)
        
        # 解码器
        decoder_layers = []
        prev_dim = latent_dim
        for hidden_dim in reversed(hidden_dims):
            decoder_layers.extend([
                nn.Linear(prev_dim, hidden_dim),
                nn.BatchNorm1d(hidden_dim),
                nn.ReLU(),
                nn.Dropout(dropout)
            ])
            prev_dim = hidden_dim
        decoder_layers.append(nn.Linear(prev_dim, input_dim))
        decoder_layers.append(nn.Sigmoid())
        self.decoder = nn.Sequential(*decoder_layers)
    
    def forward(self, x):
        latent = self.encoder(x)
        reconstructed = self.decoder(latent)
        return reconstructed, latent

class GraphAnnotationCompleter:
    """基于图的注释补全系统（解决过度平滑问题）"""
    
    def __init__(self, annotation_file: str, adj, device: torch.device = None):
        """
        初始化注释补全系统
        
        参数:
            annotation_file: 注释CSV文件路径
            adj: 图构建器实例，提供邻接矩阵
            device: 计算设备 (cuda/cpu)
        """
        self.device = device if device else torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        print(f"使用设备: {self.device}")
        
        self.data_loader = AnnotationDataLoader(annotation_file, self.device)
        
        # 确保邻接矩阵在正确的设备上
        self.adj = adj.to(self.device)
        
        self.initial_annotations = None
        self.completed_annotations = None
        self.low_dim_embeddings = None
        self.similarity_matrix = None
        
    def _normalize_adjacency(self, adj_matrix: torch.Tensor, normalization: str = 'symmetric') -> torch.Tensor:
        """
        改进的邻接矩阵归一化，避免过度平滑
        """
        adj_matrix = adj_matrix.to(self.device)
        
        # 添加自环（如果还没有）
        if torch.diag(adj_matrix).min() == 0:
            identity = torch.eye(adj_matrix.size(0), device=self.device)
            adj_matrix = adj_matrix + identity
        
        # 度矩阵
        degree = torch.diag(adj_matrix.sum(dim=1))
        
        # 添加小值避免除零错误
        epsilon = 1e-7
        
        if normalization == 'symmetric':
            # 对称归一化: S = D^{-1/2} A D^{-1/2}
            # 使用更稳定的计算方式
            degree_inv_sqrt = torch.diag(1.0 / (torch.sqrt(torch.diag(degree)) + epsilon))
            normalized_adj = torch.mm(torch.mm(degree_inv_sqrt, adj_matrix), degree_inv_sqrt)
        elif normalization == 'random_walk':  # random_walk
            # 随机游走归一化: S = D^{-1} A
            degree_inv = torch.diag(1.0 / (torch.diag(degree) + epsilon))
            normalized_adj = torch.mm(degree_inv, adj_matrix)
        else:
            print("只有symmetric和random_walk方法!")
        
        return normalized_adj
    
    def _robust_label_propagation(self, initial_labels: torch.Tensor, adj_matrix: torch.Tensor, alpha: float = 0.5, max_iter: int = 20, tol: float = 1e-4) -> torch.Tensor:
        """
        改进的标签传播，避免过度平滑
        
        关键改进:
        1. 降低alpha值（减少邻居影响）
        2. 减少最大迭代次数
        3. 增加容忍度
        4. 添加早期停止
        """
        initial_labels = initial_labels.to(self.device)
        adj_matrix = adj_matrix.to(self.device)
        
        # 使用更温和的归一化
        S = self._normalize_adjacency(adj_matrix, 'symmetric')  # 使用对称归一化
        
        Y_current = initial_labels.float()
        best_Y = Y_current.clone()
        best_diff = float('inf')
        patience = 5  # 早期停止耐心值
        patience_counter = 0
        
        for i in range(max_iter):
            # 传播步骤: Y_{t+1} = αSY_t + (1-α)Y_0
            Y_next = alpha * torch.mm(S, Y_current) + (1 - alpha) * initial_labels.float()
            
            # 检查收敛
            diff = torch.norm(Y_next - Y_current)
            
            # 早期停止策略：如果连续多次迭代改进很小，则停止
            if diff < best_diff:
                best_diff = diff
                best_Y = Y_next.clone()
                patience_counter = 0
            else:
                patience_counter += 1
                
            if diff < tol or patience_counter >= patience:
                print(f"早期停止于第 {i+1} 次迭代, 最终差异: {diff:.6f}")
                return best_Y
                
            Y_current = Y_next
        
        print(f"达到最大迭代次数 {max_iter}, 最终差异: {diff:.6f}")
        return best_Y
    
    def _sparse_label_propagation(self, initial_labels: torch.Tensor, adj_matrix: torch.Tensor, alpha: float = 0.3, k_hop: int = 1) -> torch.Tensor:
        """
        稀疏标签传播：限制传播的跳数
        """
        initial_labels = initial_labels.to(self.device)
        adj_matrix = adj_matrix.to(self.device)
        
        Y = initial_labels.float()
        
        # 只传播k跳
        for hop in range(k_hop):
            # 计算当前跳的传播
            S = self._normalize_adjacency(adj_matrix, 'symmetric')
            Y = alpha * torch.mm(S, Y) + (1 - alpha) * initial_labels.float()
            
            # 对结果进行稀疏化处理
            if hop < k_hop - 1:  # 不是最后一跳时进行稀疏化
                Y = self._sparsify_annotations(Y, sparsity=0.7)
        
        return Y
    
    def _sparsify_annotations(self, annotations: torch.Tensor, sparsity: float = 0.7) -> torch.Tensor:
        """
        对注释矩阵进行稀疏化处理，保留最重要的注释
        """
        # 对每个节点，只保留前 (1-sparsity) 比例的注释
        k = max(1, int(annotations.size(1) * (1 - sparsity)))
        
        # 创建掩码，只保留top-k值
        values, indices = torch.topk(annotations, k, dim=1)
        mask = torch.zeros_like(annotations)
        mask.scatter_(1, indices, 1.0)
        
        sparsified = annotations * mask
        return sparsified
    
    def _cosine_similarity_with_threshold(self, embeddings: torch.Tensor, threshold: float = 0.95) -> torch.Tensor:
        """
        带阈值的余弦相似性计算，避免过度相似的节点对
        """
        embeddings = embeddings.to(self.device)
        
        # 归一化
        embeddings = F.normalize(embeddings, p=2, dim=1)
        
        # 计算相似性
        similarity = torch.mm(embeddings, embeddings.t())
        
        # 应用阈值：将过高的相似度降低
        # if threshold < 1.0:
        #     # 对超过阈值的位置进行缩放
        #     mask = similarity > threshold
        #     scaling_factor = 0.8  # 缩放因子
        #     similarity[mask] = threshold + (similarity[mask] - threshold) * scaling_factor
        
        return similarity
    
    def _improved_autoencoder_reduction(self, completed_annotations: torch.Tensor, latent_dim: int = 32, epochs: int = 100) -> torch.Tensor:
        """
        改进的自编码器降维，增加正则化
        """
        completed_annotations = completed_annotations.to(self.device)
        
        autoencoder = ImprovedAutoencoder(
            completed_annotations.size(1), 
            latent_dim=latent_dim
        ).to(self.device)
        
        # 使用带权重衰减的优化器
        optimizer = torch.optim.Adam(autoencoder.parameters(), lr=0.001, weight_decay=1e-5)
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=10, factor=0.5)
        
        for epoch in range(epochs):
            reconstructed, latent = autoencoder(completed_annotations)
            loss = F.mse_loss(reconstructed, completed_annotations)
            
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            scheduler.step(loss)
            
            if epoch % 20 == 0:
                print(f"自编码器训练 epoch {epoch}/{epochs}, 损失: {loss.item():.6f}")
        
        with torch.no_grad():
            _, low_dim_embeddings = autoencoder(completed_annotations)
        
        return low_dim_embeddings
    
    def fit(self, alpha: float = 0.5, latent_dim: int = 32, 
           similarity_metric: str = 'cosine', propagation_method: str = 'robust',
           similarity_threshold: float = 0.95, k_hop: int = 2) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        执行完整的注释补全流程（改进版本）
        
        参数:
            alpha: 标签传播参数（建议0.3-0.5）
            latent_dim: 降维后的维度
            similarity_metric: 相似性计算方法 ('cosine' 或 'jaccard')
            propagation_method: 标签传播方法 ('robust' 或 'sparse')
            similarity_threshold: 相似性阈值，避免过度相似
            k_hop: 稀疏传播的跳数
            
        返回:
            补全后的注释矩阵和相似性矩阵
        """
        # 1. 加载初始注释数据
        print("加载注释数据...")
        self.initial_annotations = self.data_loader.load_annotations()
        
        # 确保邻接矩阵在正确的设备上
        adj_matrix = self.adj.to(self.device)
        
        # 2. 改进的标签传播
        print("进行标签传播...")
        if propagation_method == 'sparse':
            self.completed_annotations = self._sparse_label_propagation(
                self.initial_annotations, adj_matrix, alpha, k_hop
            )
        else:  # robust
            self.completed_annotations = self._robust_label_propagation(
                self.initial_annotations, adj_matrix, alpha
            )
        
        # 3. 对传播结果进行稀疏化处理
        print("对传播结果进行稀疏化...")
        self.completed_annotations = self._sparsify_annotations(self.completed_annotations, sparsity=0.4)
        
        # 4. 改进的降维
        print("进行降维...")
        if latent_dim < self.completed_annotations.size(1):
            self.low_dim_embeddings = self._improved_autoencoder_reduction(
                self.completed_annotations, latent_dim
            )
        else:
            self.low_dim_embeddings = self.completed_annotations
        
        # 5. 改进的相似性计算
        print("计算语义相似性...")
        if similarity_metric == 'cosine':
            self.similarity_matrix = self._cosine_similarity_with_threshold(
                self.low_dim_embeddings, similarity_threshold
            )
        else:  # jaccard
            self.similarity_matrix = self._jaccard_similarity_topk(
                self.completed_annotations
            )
        
        # 分析相似性分布
        self._analyze_similarity_distribution()
        
        print(f"补全完成 - 注释矩阵形状: {self.completed_annotations.shape}")
        print(f"相似性矩阵形状: {self.similarity_matrix.shape}")
        
        return self.completed_annotations, self.similarity_matrix
    
    def _analyze_similarity_distribution(self):
        """分析相似性矩阵的分布"""
        if self.similarity_matrix is None:
            return
            
        sim_values = self.similarity_matrix.cpu().numpy()
        np.fill_diagonal(sim_values, np.nan)  # 忽略对角线
        
        print(f"相似性统计:")
        print(f"  平均值: {np.nanmean(sim_values):.4f}")
        print(f"  标准差: {np.nanstd(sim_values):.4f}")
        print(f"  最小值: {np.nanmin(sim_values):.4f}")
        print(f"  最大值: {np.nanmax(sim_values):.4f}")
        
        # 检查是否有过度相似问题
        high_sim_ratio = np.sum(sim_values > 0.95) / np.sum(~np.isnan(sim_values))
        if high_sim_ratio > 0.5:
            print(f"警告: {high_sim_ratio:.1%} 的节点对相似度超过0.95，可能存在过度平滑")
    
    # 其他方法保持不变...
    def predict_annotations(self, node_indices: List[int], threshold: float = 0.5) -> torch.Tensor:
        """预测特定节点的注释"""
        if self.completed_annotations is None:
            raise ValueError("请先调用fit方法进行训练")
            
        predictions = self.completed_annotations[node_indices]
        binary_predictions = (predictions > threshold).float()
        return binary_predictions
    
    def get_functional_similarity(self, node_i: int, node_j: int) -> float:
        """获取两个节点的功能相似性"""
        if self.similarity_matrix is None:
            raise ValueError("请先调用fit方法进行训练")
            
        return self.similarity_matrix[node_i, node_j].item()
    
    def get_gene_annotations(self, gene_name: str) -> torch.Tensor:
        """获取特定基因的补全注释"""
        if self.completed_annotations is None:
            raise ValueError("请先调用fit方法进行训练")
            
        gene_idx = self.data_loader.get_gene_index(gene_name)
        if gene_idx == -1:
            raise ValueError(f"基因名 '{gene_name}' 不存在于数据中")
            
        return self.completed_annotations[gene_idx]
      
    def cleanup(self):
        """释放实例持有的所有 GPU 张量"""
        self.initial_annotations = None
        self.completed_annotations = None
        self.low_dim_embeddings = None
        self.similarity_matrix = None
        self.adj = None  # 如果有需要，也可以释放
        torch.cuda.empty_cache()
