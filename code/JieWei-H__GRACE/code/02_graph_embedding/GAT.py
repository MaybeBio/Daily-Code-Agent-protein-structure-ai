from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Literal, List

import torch
import torch.nn as nn
import torch.nn.functional as F
import os
from pathlib import Path
from typing import Literal, Optional, Union
from tqdm import tqdm
import gc
from AttentionPooling import SelfAttentionPooling, process_esm2_directory, get_gpu_memory
from GraphBuilder import PPIGraphBuilder

class GATConfig:
    def __init__(self,
                 in_feats: int = 1280,
                 out_feats: int = 512,
                 heads: int = 8,
                 concat: bool = True,
                 negative_slope: float = 0.2,
                 dropout_attn: float = 0.6,
                 dropout_feat: float = 0.6,
                 residual: bool = True,
                 bias: bool = True,
                 n_layers: int = 3,
                 pooling_hidden_ratio: float = 0.25,
                 pooling_activation: str = 'tanh'):
        """
        GAT模型配置类
        
        参数说明：
        in_feats: 输入特征维度 (默认: 1280)
        out_feats: 输出特征维度 (默认: 512)
        heads: 注意力头数量 (默认: 8)
        concat: 是否拼接多头输出 (默认: True)
        negative_slope: LeakyReLU负斜率 (默认: 0.2)
        dropout_attn: 注意力系数dropout率 (默认: 0.6)
        dropout_feat: 特征dropout率 (默认: 0.6)
        residual: 是否使用残差连接 (默认: True)
        bias: 是否使用偏置项 (默认: True)
        n_layer: 嵌入层数量 (默认: 3)
        pooling_hidden_ratio: 池化层隐藏层比例 (默认: 0.25)
        pooling_activation: 池化层激活函数 (默认: 'tanh')
        """
        self.in_feats = in_feats
        self.out_feats = out_feats
        self.heads = heads
        self.concat = concat
        self.negative_slope = negative_slope
        self.dropout_attn = dropout_attn
        self.dropout_feat = dropout_feat
        self.residual = residual
        self.bias = bias
        self.n_layers = n_layers
        self.pooling_hidden_ratio = pooling_hidden_ratio
        self.pooling_activation = pooling_activation

## 单注意力头
class GATHead(nn.Module):
    """
    Shapes:
        X: [N, F_in]
        Wh: [N, F_out]
        a: [2*F_out, 1]
        e: [N, N] (masked with adjacency)
        alpha: [N, N]
        output: [N, F_out]
    """
    def __init__(self, in_feats: int, out_feats: int, negative_slope: float = 0.2, bias: bool = True):
        super().__init__()
        self.lin = nn.Linear(in_feats, out_feats, bias=False)  # 线性变换层
        self.att = nn.Parameter(torch.empty(2 * out_feats, 1))  # 注意力参数向量a
        self.leakyrelu = nn.LeakyReLU(negative_slope)  # LeakyReLU激活函数
        self.bias = nn.Parameter(torch.zeros(out_feats)) if bias else None  # 偏置项
        self.reset_parameters()  # 初始化参数

    def reset_parameters(self):
        nn.init.xavier_uniform_(self.lin.weight)  # Xavier均匀初始化线性层权重
        nn.init.xavier_uniform_(self.att)  # Xavier均匀初始化注意力参数
        if self.bias is not None:
            nn.init.zeros_(self.bias)  # 零初始化偏置

    def forward(self, X: torch.Tensor, adj: torch.Tensor) -> torch.Tensor:
        N = X.size(0)  # 节点数量
        Wh = self.lin(X)  # 线性变换 [N, F_out]
        
        # 计算注意力得分 e_ij = a^T [Wh_i || Wh_j]
        Wh_i = Wh.unsqueeze(1).expand(N, N, -1)  # 扩展维度 [N,1,F_out] -> [N, N, F_out]
        Wh_j = Wh.unsqueeze(0).expand(N, N, -1)  # 扩展维度 [1,N,F_out] -> [N, N, F_out]
        cat = torch.cat([Wh_i, Wh_j], dim=-1)  # 拼接 [N, N, 2*F_out]
        e = self.leakyrelu(cat @ self.att).squeeze(-1)  # 计算注意力得分 [N, N]
        
        # 使用邻接矩阵掩码：无边处设为负无穷，softmax后为0
        neg_inf = -1e9  # 负无穷近似值
        e_masked = e.masked_fill(adj <= 0, neg_inf)  # 应用掩码
        
        # 对每个节点的邻居进行softmax归一化
        alpha = F.softmax(e_masked, dim=-1)  # [N, N]
        
        # 邻居特征的加权和
        out = alpha @ Wh  # [N, F_out]
        if self.bias is not None:
            out = out + self.bias  # 添加偏置
        return out

## 多头注意力层
class GATLayer(nn.Module):
    def __init__(self, config: GATConfig):
        super().__init__()
        self.cfg = config  # 存储配置
        Head = GATHead
        # 创建多头注意力
        self.heads = nn.ModuleList([
            Head(config.in_feats, config.out_feats, config.negative_slope, config.bias)
            for _ in range(config.heads)
        ])
        self.feat_drop = nn.Dropout(config.dropout_feat)  # 特征dropout
        self.attn_drop = nn.Dropout(config.dropout_attn)  # 注意力dropout
        
        # 如果需要残差连接且输入输出维度不匹配，创建投影层
        out_dim = config.out_feats * config.heads if config.concat else config.out_feats
        self.res_proj = None
        if config.residual and config.in_feats != out_dim:
            self.res_proj = nn.Linear(config.in_feats, out_dim, bias=False)

    def forward(self, X: torch.Tensor, adj: torch.Tensor, activation: Optional[nn.Module] = F.elu) -> torch.Tensor:
        Xd = self.feat_drop(X)  # 应用特征dropout
        
        # 计算每个头的输出
        head_outs = []
        for head in self.heads:
            out = head(Xd, adj)  # [N, F_out]
            out = self.attn_drop(out)  # 应用注意力dropout
            head_outs.append(out)
            
        # 拼接或平均多头输出
        if self.cfg.concat:
            H = torch.cat(head_outs, dim=-1)  # [N, heads*out_feats]
        else:
            H = torch.stack(head_outs, dim=0).mean(dim=0)  # [N, out_feats]
        
        # 残差连接
        if self.cfg.residual:
            if self.res_proj is not None:
                H = H + self.res_proj(X)  # 使用投影层
            else:
                H = H + X  # 直接相加
        
        # 激活函数
        if activation is not None:
            H = activation(H)
        return H
      
class MultiLayerGAT(nn.Module):
    def __init__(self, config: GATConfig):
        super().__init__()
        self.layers = nn.ModuleList()
        self.n_layers = config.n_layers
        
        # 输入层
        self.layers.append(GATLayer(GATConfig(
            in_feats=config.in_feats,
            out_feats=config.out_feats,
            heads=config.heads,
            concat=config.concat,
            negative_slope=config.negative_slope,
            dropout_attn=config.dropout_attn,
            dropout_feat=config.dropout_feat,
            residual=config.residual,
        )))
        
        # 隐藏层
        for _ in range(config.n_layers - 1):
            self.layers.append(GATLayer(GATConfig(
                in_feats=config.out_feats * config.heads,  # 因为concat=True
                out_feats=config.out_feats,
                heads=config.heads,
                concat=config.concat,
                negative_slope=config.negative_slope,
                dropout_attn=config.dropout_attn,
                dropout_feat=config.dropout_feat,
                residual=config.residual,
            )))
        
        # self.layers.append(GATLayer(GATConfig(
        #         in_feats=config.out_feats * config.heads,  # 因为中间层拼接，所以输入是out_feats * heads
        #         out_feats=config.out_feats,
        #         heads=config.heads,
        #         concat=False,  # 最后一层不拼接，取平均
        #         negative_slope=config.negative_slope,
        #         dropout_attn=config.dropout_attn,
        #         dropout_feat=config.dropout_feat,
        #         residual=config.residual,
        #     )))
        
    def forward(self, X: torch.Tensor, adj: torch.Tensor) -> torch.Tensor:
        H = X
        for i, layer in enumerate(self.layers):
            # 除了最后一层，其他层都使用ELU激活
            activation = F.elu if i < self.n_layers - 1 else None
            H = layer(H, adj, activation=activation)
        return H

class IntegratedModel(nn.Module): 
    """整合AttentionPooling和GAT的模型"""
    def __init__(self, config: GATConfig, graph_builder: PPIGraphBuilder):
        super().__init__()
        self.adj = graph_builder.adj
        
        # 初始化AttentionPooling层
        self.attention_pooling = SelfAttentionPooling(
            input_dim=config.in_feats,
            hidden_ratio=config.pooling_hidden_ratio,
            activation=config.pooling_activation
        )
        
        # 初始化GAT层
        self.gat = MultiLayerGAT(config)
        
        self.output_projection = nn.Linear(
            config.out_feats * config.heads,  # 输入维度
            config.out_feats  # 输出维度
        )
        
    def forward(self, node_features, subgraph_adj) -> torch.Tensor:
        """
        前向传播
        
        Args:
            node_sequences: 节点序列列表，每个序列形状为 [L_i, 1280]
            adj: 邻接矩阵，形状为 [N, N]
            
        Returns:
            GAT输出，形状为 [N, out_feats]
        """
        # 对每个节点序列进行注意力池化
        pooled_features = []
        
        for seq in node_features:
            pooled = self.attention_pooling(seq.unsqueeze(0))  # 添加批次维度
            pooled_features.append(pooled.squeeze(0))  # 移除批次维度
        
        # 堆叠所有节点的特征
        X = torch.stack(pooled_features, dim=0)  # [N, 1280]
        
        # 通过GAT层
        H = self.gat(X, subgraph_adj)
        
        H = self.output_projection(H)
        
        return H

class GAT_Model(nn.Module):
    """整合生物信息约束的多任务GAT模型"""
    def __init__(self, config, graph_builder):
        super().__init__()
        self.config = config
        
        # 共享的特征提取层（GAT + AttentionPooling）
        self.feature_extractor = IntegratedModel(config, graph_builder)
        
        # PPI预测头（链接预测）
        self.ppi_predictor = nn.Sequential(
            nn.Linear(2 * config.out_feats, 256),
            nn.ReLU(),
            nn.Dropout(0.5),
            nn.Linear(256, 1),
            nn.Sigmoid()
        )
        
    def forward(self, node_sequences, adj, node1_idx=None, node2_idx=None):
        """
        前向传播
        
        参数:
        node_sequences: 节点序列列表
        adj: 邻接矩阵
        node1_idx, node2_idx: 用于PPI预测的节点索引（训练时提供）
        """
        # 提取节点特征
        node_embeddings = self.feature_extractor(node_sequences, adj)  # [N, out_feats]
        
        outputs = {}
        
        # PPI预测
        if node1_idx is not None and node2_idx is not None:
            emb1 = node_embeddings[node1_idx]
            emb2 = node_embeddings[node2_idx]
            pair_emb = torch.cat([emb1, emb2], dim=-1)
            ppi_score = self.ppi_predictor(pair_emb)
            outputs['ppi'] = ppi_score
        
        return outputs, node_embeddings
      
