import os
import csv
import sys
import argparse
import time
import math
import warnings
import torch
import torch.distributed as dist
from torch import optim, nn
import torch.nn.functional as F
from contextlib import nullcontext
from tqdm import tqdm
from GraphBuilder import PPIGraphBuilder
from PPIData import PPIDataset, PPIDataLoader
import pickle
import numpy as np
import pandas as pd
from Annotation import GraphAnnotationCompleter
import random
import gc

warnings.filterwarnings('ignore')

def integrate_similarity_matrices(similarity_matrices: list[torch.Tensor], 
                                 weights: list[float] = None,
                                 set_diagonal_zero: bool = True) -> torch.Tensor:
    """
    整合多个相似性矩阵
    
    参数:
        similarity_matrices: 相似性矩阵列表 [GO, KEGG, Sublocation]
        weights: 各矩阵的权重，None表示等权平均
        set_diagonal_zero: 是否将对角线设为0
    
    返回:
        整合后的相似性矩阵
    """
    if not similarity_matrices:
        raise ValueError("相似性矩阵列表不能为空")
    
    # 验证矩阵维度一致
    shapes = [matrix.shape for matrix in similarity_matrices]
    if len(set(shapes)) != 1:
        raise ValueError(f"相似性矩阵维度不一致: {shapes}")
    
    n_matrices = len(similarity_matrices)
    
    # 设置默认权重（等权）
    if weights is None:
        weights = [1.0 / n_matrices] * n_matrices
    elif len(weights) != n_matrices:
        raise ValueError("权重数量必须与矩阵数量一致")
    
    # 验证权重和为1（允许微小误差）
    weight_sum = sum(weights)
    if abs(weight_sum - 1.0) > 1e-6:
        print(f"警告: 权重和({weight_sum})不等于1，将自动归一化")
        weights = [w / weight_sum for w in weights]
    
    # 加权平均
    integrated_sim = torch.zeros_like(similarity_matrices[0])
    for i, (matrix, weight) in enumerate(zip(similarity_matrices, weights)):
        integrated_sim += weight * matrix
    
    # 将对角线设为0
    if set_diagonal_zero:
        n_nodes = integrated_sim.shape[0]
        integrated_sim[range(n_nodes), range(n_nodes)] = 0.0
    
    return integrated_sim
  

def build_combined_bias(G, similarity, num_special_tokens=6, bias_value=1.0):
    """
    整合图结构偏置和生物相似性偏置，保存为稀疏或密集张量。
    参数:
        G: networkx.Graph，节点为0..N-1整数
        similarity: torch.Tensor，形状 (N, N)，节点间的相似性值
        num_special_tokens: 特殊token数量（假设索引0~5为特殊token）
        bias_value: 图偏置的常数（仅用于图边的基础值）
        mode: 'multiply' 或 'add'
        filename: 输出文件路径
    返回:
        combined: torch.Tensor（可能稀疏或密集）
    """
    # 检查节点连续性
    nodes = list(G.nodes())
    if set(nodes) != set(range(len(nodes))):
        raise ValueError("图节点必须是从0开始的连续整数，请先重映射节点ID")
    N = len(nodes)
    vocab_size = num_special_tokens + N

    # 构建图偏置的索引（有向边双向）
    indices = []
    for u, v in G.edges():
        src_u = u + num_special_tokens
        src_v = v + num_special_tokens
        tgt_u = v + num_special_tokens
        tgt_v = u + num_special_tokens
        indices.append([src_u, tgt_u])
        indices.append([src_v, tgt_v])
    indices = torch.tensor(indices, dtype=torch.long).t()  # (2, 2*|E|)

    # 乘法：从similarity中取出对应位置的值，乘上bias_value
    # 注意：similarity是原始节点索引，需要转换为词汇表索引
    row_nodes = indices[0] - num_special_tokens
    col_nodes = indices[1] - num_special_tokens
    sim_vals = similarity[row_nodes, col_nodes]  # 取出对应相似度
    values = bias_value * sim_vals
    # 构建稀疏张量
    combined = torch.sparse_coo_tensor(indices, values, (vocab_size, vocab_size))
    print(f"乘法组合偏置已保存，形状 {combined.shape}，非零数 {indices.size(1)}")

    return combined

# 使用示例（假设你的图变量名为 G）
# save_adjacency_bias(G, 'ppi_adj_bias.pt')
if __name__ == "__main__":
    
    # 检查文件是否存在
    if os.path.exists("graph_builder.pt"):
        # 如果文件存在，直接加载
        graph_builder = torch.load("graph_builder.pt")
    else:
        # 如果文件不存在，初始化并构建
        graph_builder = PPIGraphBuilder(args.node_dir, args.ppi_file)
        torch.save(graph_builder, "graph_builder.pt")
    
    
    ##################################### 生物注释嵌入 
    similarity_matrices = []
    # GO
    annotation_go = GraphAnnotationCompleter("../GraphData/GO_matrix.csv", graph_builder.adj, device="cuda")
    # 执行完整的注释补全流程
    completed_annotations_go, similarity_matrix_go = annotation_go.fit(
        alpha=0.3,                    # 降低传播强度
        propagation_method='sparse',   # 使用稀疏传播
        k_hop=1,                      # 限制传播跳数
        similarity_threshold=0.9,      # 设置相似性阈值
        # latent_dim=100                 # 增加潜在维度
    )
    similarity_matrices.append(similarity_matrix_go.to("cpu"))
    
    annotation_go.cleanup()
    gc.collect()
    torch.cuda.empty_cache()

    
    # KEGG
    annotation_kegg = GraphAnnotationCompleter("../GraphData/KEGG_matrix.csv", graph_builder.adj, device="cuda")
    # 执行完整的注释补全流程
    completed_annotation_kegg, similarity_matrix_kegg = annotation_kegg.fit(
        alpha=0.3,                    # 降低传播强度
        propagation_method='sparse',   # 使用稀疏传播
        k_hop=1,                      # 限制传播跳数
        similarity_threshold=0.9,      # 设置相似性阈值
        # latent_dim=100                 # 增加潜在维度
    )
    similarity_matrices.append(similarity_matrix_kegg.to("cpu"))
    
    annotation_kegg.cleanup()
    gc.collect()
    torch.cuda.empty_cache()
    
    # Sublocation
    annotation_sublocation = GraphAnnotationCompleter("../GraphData/Sublocation_matrix.csv", graph_builder.adj, device="cpu")
    # 执行完整的注释补全流程
    completed_annotation_sublocation, similarity_matrix_sublocation = annotation_sublocation.fit(
        alpha=0.3,                    # 降低传播强度
        propagation_method='sparse',   # 使用稀疏传播
        k_hop=1,                      # 限制传播跳数
        similarity_threshold=0.9,      # 设置相似性阈值
        # latent_dim=50                 # 增加潜在维度
    )
    similarity_matrices.append(similarity_matrix_sublocation)
    
    annotation_sublocation.cleanup()
    gc.collect()
    torch.cuda.empty_cache()
    
    custom_weights = [0.4, 0.4, 0.2]
    integrated_similarity = integrate_similarity_matrices(
        similarity_matrices, 
        weights=custom_weights
    )
    
    # 加载全图结构
    with open('./graph.pkl', 'rb') as f:
        graph = pickle.load(f)
    
    graph_bais = build_combined_bias(graph, integrated_similarity)
    
    torch.save(graph_bais, 'integrated_similarity_All.pt')
    
    
