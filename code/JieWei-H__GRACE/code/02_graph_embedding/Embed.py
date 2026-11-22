import torch
import pickle
import numpy as np
from GAT import GATConfig, GAT_Model
from GraphBuilder import PPIGraphBuilder
import os
from tqdm import tqdm

def load_model_and_compute_embeddings(model_path, graph_builder, device='cpu', batch_size=256):
    """
    加载训练好的模型并分批计算所有节点的嵌入特征
    
    参数:
        model_path: 模型检查点路径
        graph_builder: 图构建器实例
        device: 计算设备
        batch_size: 批次大小
    
    返回:
        node_embeddings: 所有节点的嵌入特征
        node_id_to_embedding: 节点ID到嵌入向量的映射
    """
    # 加载模型配置（需要与训练时相同）
    config = GATConfig(
        out_feats=512,  # 与训练时保持一致
        n_layers=4,     # 与训练时保持一致
        in_feats=1280   # 与训练时保持一致
    )
    
    # 初始化模型
    model = GAT_Model(config, graph_builder)
    model = model.to(device)
    
    # 加载模型权重
    checkpoint = torch.load(model_path, map_location=device)
    model.load_state_dict(checkpoint['model_state_dict'])
    model.eval()  # 设置为评估模式
    
    print(f"成功加载模型: {model_path}")
    print(f"模型训练轮次: {checkpoint.get('epoch', '未知')}")
    print(f"模型损失: {checkpoint.get('loss', '未知'):.4f}")
    
    # 获取所有节点索引
    all_node_indices = list(range(graph_builder.num_nodes))
    full_adj_matrix = graph_builder.adj.to(device)
    
    # 分批处理节点
    print(f"开始分批处理 {len(all_node_indices)} 个节点，批次大小: {batch_size}")
    
    all_embeddings = []
    node_id_to_embedding = {}
    
    # 创建进度条
    progress_bar = tqdm(total=len(all_node_indices), desc="计算节点嵌入")
    
    for start_idx in range(0, len(all_node_indices), batch_size):
        end_idx = min(start_idx + batch_size, len(all_node_indices))
        batch_indices = all_node_indices[start_idx:end_idx]
        
        # 获取当前批次的节点特征
        batch_node_features = [graph_builder.node_features[i].to(device) for i in batch_indices]
        
        # 获取当前批次的子图邻接矩阵
        batch_adj = full_adj_matrix[batch_indices, :][:, batch_indices]
        
        # 创建虚拟节点对（用于前向传播，但不会影响嵌入计算）
        dummy_node1_idx = torch.tensor([0], device=device)
        dummy_node2_idx = torch.tensor([0], device=device)
        
        # 计算当前批次的节点嵌入
        with torch.no_grad():
            outputs, batch_embeddings = model(
                batch_node_features, 
                batch_adj, 
                dummy_node1_idx, 
                dummy_node2_idx
            )
        
        # 将当前批次的嵌入添加到总列表中
        batch_embeddings_np = batch_embeddings.cpu().numpy()
        all_embeddings.append(batch_embeddings_np)
        
        # 更新节点ID到嵌入的映射
        for i, node_idx in enumerate(batch_indices):
            # 找到对应的节点ID
            for node_id, idx in graph_builder.node_id_to_idx.items():
                if idx == node_idx:
                    node_id_to_embedding[node_id] = batch_embeddings_np[i]
                    break
        
        # 更新进度条
        progress_bar.update(len(batch_indices))
    
    progress_bar.close()
    
    # 按原始顺序拼接所有批次的嵌入
    node_embeddings = np.vstack(all_embeddings)
    
    print(f"成功计算 {len(node_embeddings)} 个节点的嵌入特征")
    print(f"嵌入维度: {node_embeddings.shape[1]}")
    
    return node_embeddings, node_id_to_embedding

# 使用示例
if __name__ == "__main__":
    
    # 初始化图构建器（需要与训练时相同的参数）
    graph_builder = torch.load("graph_builder.pt")
    
    # 设置设备
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    print(f"使用设备: {device}")
    
    # 设置批次大小（根据可用内存调整）
    batch_size = 128  # 可以根据需要调整
    
    ############# 模型1嵌入
    # 加载模型并计算嵌入
    model_path = "out-1/model_epoch_2_final.pth"  # 替换为您的模型路径
    embeddings, node_id_to_embedding = load_model_and_compute_embeddings(
        model_path, graph_builder, device=device, batch_size=batch_size
    )
    
    # --- 新增：生成特殊token嵌入 ---
    num_special = 6                     # 特殊token数量
    embed_dim = embeddings.shape[1]     # 512
    torch.manual_seed(42)               # 固定随机种子，保证可复现
    special_embeddings = torch.randn(num_special, embed_dim)  # 标准正态分布

    # 将图节点嵌入转为torch tensor并合并
    node_embeddings_tensor = torch.from_numpy(embeddings)     # (N, 512)
    full_embeddings = torch.cat([special_embeddings, node_embeddings_tensor], dim=0)  # (N+6, 512)

    # 保存完整嵌入矩阵（按词汇表顺序：前6为特殊token，后N为图节点）
    torch.save(full_embeddings, "node_embeddings_PPI.pt")
    print(f"完整嵌入矩阵已保存，形状: {full_embeddings.shape}")


    ############# 模型2嵌入
    # 加载模型并计算嵌入
    model_path = "out-2/model_epoch_2_final.pth"  # 替换为您的模型路径
    embeddings, node_id_to_embedding = load_model_and_compute_embeddings(
        model_path, graph_builder, device=device, batch_size=batch_size
    )
    
    # --- 新增：生成特殊token嵌入 ---
    num_special = 6                     # 特殊token数量
    embed_dim = embeddings.shape[1]     # 512
    torch.manual_seed(42)               # 固定随机种子，保证可复现
    special_embeddings = torch.randn(num_special, embed_dim)  # 标准正态分布

    # 将图节点嵌入转为torch tensor并合并
    node_embeddings_tensor = torch.from_numpy(embeddings)     # (N, 512)
    full_embeddings = torch.cat([special_embeddings, node_embeddings_tensor], dim=0)  # (N+6, 512)

    # 保存完整嵌入矩阵（按词汇表顺序：前6为特殊token，后N为图节点）
    torch.save(full_embeddings, "node_embeddings_Cosine.pt")
    print(f"完整嵌入矩阵已保存，形状: {full_embeddings.shape}")
