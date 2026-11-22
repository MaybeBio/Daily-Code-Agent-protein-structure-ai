import networkx as nx
import numpy as np
import time
import random
import os
import pickle
import json
import sys
from tqdm import tqdm
import gc
from collections import deque

class TokenIDGene:
    def __init__(self):
        self.gene_to_id = {}  # 正向映射：gene → id
        self.id_to_gene = {}  # 反向映射：id → gene

    def add_mapping(self, gene, id):
        """添加双向映射关系"""
        self.gene_to_id[gene] = id
        self.id_to_gene[id] = gene

    def get_id(self, gene):
        """通过gene获取id，不存在时返回None"""
        return self.gene_to_id.get(gene)

    def get_gene(self, id):
        """通过id获取gene，不存在时返回None"""
        return self.id_to_gene.get(id)

class GraphFeatureProcessor:
    """图特征处理器 - 负责节点特征计算和核心节点选择"""
    
    def __init__(self, global_ppi, feature_weights=None, normalization_strategy="minmax"):
        """
        初始化特征处理器
        
        参数:
        global_ppi: 全局PPI图
        feature_weights: 特征权重字典
        normalization_strategy: 归一化策略
        """
        self.global_ppi = global_ppi
        
        # 快速计算全局度中心性
        print("计算度中心性...")
        start_time = time.time()
        self.global_degrees = dict(global_ppi.degree())
        print(f"度中心性计算完成，耗时: {time.time()-start_time:.2f}秒")
        
        # 默认特征权重（只保留度相关特征）
        self.default_weights = {
            'local_degree': 0.7,
            'global_degree': 0.3
        }
        
        # 应用自定义权重
        self.feature_weights = self.default_weights.copy()
        if feature_weights:
            self.feature_weights.update(feature_weights)
            
        self.normalization_strategy = normalization_strategy
    
    def get_normalized_features(self, subgraph):
        """
        获取子图中所有节点的归一化特征（只计算度）
        
        返回:
        dict: {node: {feature: normalized_value}}
        """
        # 计算所有节点的原始特征
        all_features = {}
        degrees = dict(subgraph.degree())  # 一次性计算所有节点的局部度
        
        for node in subgraph.nodes():
            features = {
                'local_degree': degrees[node],
                'global_degree': self.global_degrees.get(node, 0)
            }
            all_features[node] = features
        
        # 提取特征矩阵
        feature_matrix = {feat: [] for feat in self.default_weights}
        for node, feats in all_features.items():
            for feat in self.default_weights:
                feature_matrix[feat].append(feats[feat])
        
        # 归一化处理
        normalized_features = {}
        for feat, values in feature_matrix.items():
            if self.normalization_strategy == "minmax":
                min_val = min(values)
                max_val = max(values)
                range_val = max_val - min_val if max_val > min_val else 1
                normalized = [(v - min_val) / range_val for v in values]
            else:  # z-score
                mean_val = sum(values) / len(values)
                std_val = (sum((v - mean_val) ** 2 for v in values) / len(values)) ** 0.5
                std_val = std_val if std_val > 0 else 1
                normalized = [(v - mean_val) / std_val for v in values]
            
            for i, node in enumerate(subgraph.nodes()):
                if node not in normalized_features:
                    normalized_features[node] = {}
                normalized_features[node][feat] = normalized[i]
        
        return normalized_features
    
    def calculate_node_score(self, normalized_features, node):
        """
        计算节点综合得分（仅基于度）
        """
        # 基本加权得分
        score = 0
        for feat, weight in self.feature_weights.items():
            score += normalized_features[node][feat] * weight
        
        return score
    
    def select_core_nodes(self, subgraph, top_percent=0.2, random_seed = None):
        """
        选择核心节点：计算节点得分并选择前top_percent的节点
        
        参数:
        subgraph: 输入子图
        top_percent: 选择前多少比例的节点作为核心节点
        
        返回:
        tuple: (sorted_nodes, core_nodes, node_scores)
            - sorted_nodes: 按得分排序的所有节点
            - core_nodes: 选出的核心节点列表
            - node_scores: 所有节点的得分字典
        """
        # 获取归一化特征
        normalized_features = self.get_normalized_features(subgraph)
        
        # 计算节点得分
        node_scores = {}
        for node in subgraph.nodes():
            node_scores[node] = self.calculate_node_score(normalized_features, node)
        
        # 按得分排序
        sorted_nodes = sorted(
            subgraph.nodes(),
            key=lambda x: node_scores[x],
            reverse=True
        )
        
        # 选择前top_percent作为核心节点
        num_core = max(1, int(len(sorted_nodes) * top_percent))
        core_candidates = sorted_nodes[:num_core]
        
        # 设置随机数
        if random_seed is not None:
            random.seed(random_seed)
        
        # 从候选核心结点中随机选择一个
        selected_core = random.choice(core_candidates)
        core_nodes = [selected_core]
        
        return core_nodes

class GraphSequenceGenerator:
    """图序列生成器 - 负责基于核心节点生成BFS序列和文本"""
    
    def __init__(self, token):
        """
        初始化序列生成器
        
        参数:
        token: TokenIDGene实例，用于节点ID到基因名的转换
        """
        self.token = token
    
    def bfs_traversal(self, graph, start_nodes, max_nodes=None):
        """
        从多个起始节点进行BFS遍历
        
        参数:
        graph: 输入图
        start_nodes: 起始节点列表
        max_nodes: 最大节点数限制
        
        返回:
        list: BFS遍历的节点序列
        """
        visited = set()
        queue = deque()
        traversal_order = []
        
        # 将所有起始节点加入队列
        for node in start_nodes:
            if node not in visited:
                visited.add(node)
                queue.append(node)
                traversal_order.append(node)
        
        # 执行BFS
        while queue:
            current = queue.popleft()
            
            # 遍历邻居节点
            for neighbor in graph.neighbors(current):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
                    traversal_order.append(neighbor)
                    
                    # 如果达到最大节点数限制，提前终止
                    if max_nodes and len(traversal_order) >= max_nodes:
                        return traversal_order
        
        return traversal_order
    
    def generate_bfs_sequence(self, subgraph, core_nodes, strategy="single_start_bfs"):
        """
        基于核心节点生成BFS序列
        
        参数:
        subgraph: 输入子图
        core_nodes: 核心节点列表
        strategy: 序列生成策略
            - "multi_start_bfs": 从多个核心节点开始BFS
            - "single_start_bfs": 从得分最高的核心节点开始BFS
            - "core_first_then_bfs": 先列核心节点再BFS
        
        返回:
        list: 节点ID序列
        """
        if strategy == "multi_start_bfs":
            # 从所有核心节点开始BFS
            sequence = self.bfs_traversal(subgraph, core_nodes)
        
        elif strategy == "single_start_bfs":
            # 仅从得分最高的核心节点开始BFS
            if core_nodes:
                sequence = self.bfs_traversal(subgraph, core_nodes)
            else:
                sequence = list(subgraph.nodes())
        else:
            # 默认使用单起点BFS
            sequence = self.bfs_traversal(subgraph, core_nodes)
        
        return sequence
    
    def sequence_to_text(self, node_sequence):
        """
        将节点序列转换为文本
        
        参数:
        node_sequence: 节点ID序列
        
        返回:
        str: 文本序列
        """
        tokens = []
        for node in node_sequence:
            # 将节点ID转换为基因名
            gene_name = self.token.id_to_gene.get(node, str(node))
            tokens.append(gene_name)
        
        return " ".join(tokens)

class TrainingDataBuilder:
    """训练数据集构建器 - 单线程版（适用于Windows系统）"""
    
    def __init__(self, feature_processor, sequence_generator):
        """
        初始化数据集构建器
        
        参数:
        feature_processor: GraphFeatureProcessor实例
        sequence_generator: GraphSequenceGenerator实例
        """
        self.feature_processor = feature_processor
        self.sequence_generator = sequence_generator
    
    def encode_subgraph(self, subgraph, core_node_percent=0.3, sequence_strategy="single_start_bfs", random_seed=None):
        """
        编码子图为文本序列
        
        参数:
        subgraph: 输入子图
        core_node_percent: 核心节点比例
        sequence_strategy: 序列生成策略
        
        返回:
        str: 编码后的文本序列
        """
        try:
            # 1. 特征处理和核心节点选择
            core_nodes = self.feature_processor.select_core_nodes(
                subgraph, core_node_percent, random_seed
            )
            
            # 2. 基于核心节点生成BFS序列
            node_sequence = self.sequence_generator.generate_bfs_sequence(
                subgraph, core_nodes, sequence_strategy
            )
            
            # 3. 将序列转换为文本
            text_sequence = self.sequence_generator.sequence_to_text(node_sequence)
            
            return text_sequence
        except Exception as e:
            print(f"子图编码失败: {str(e)}")
            return ""  # 返回空字符串避免中断
    
    def build_sft_data(self, noisy_subgraphs, output_path, chunk_size=100):
        """
        构建预训练数据集 - 单线程优化
        """
        sft_data = []
        start_time = time.time()
        total_subgraphs = len(noisy_subgraphs)
        
        # 使用单线程处理所有子图
        with tqdm(total=total_subgraphs, desc="构建预训练数据") as pbar:
            # 收集所有编码片段
            fragments = []
            
            for i, subgraph in enumerate(noisy_subgraphs):
                try:
                    # 编码子图
                    encoded = self.encode_subgraph(subgraph, random_seed=i)
                    fragments.append(f"<|im_start|>{encoded}<|im_end|>")
                except Exception as e:
                    print(f"子图 {i} 编码失败: {str(e)}")
                
                # 更新进度条
                pbar.update(1)
                
                # 每处理10000个输出进度
                if (i + 1) % 10000 == 0:
                    print(f"已处理 {i+1}/{total_subgraphs} 个子图")
            
            # 将片段分块组合成大文本
            chunks = []
            for j in range(0, len(fragments), chunk_size):
                chunk = " ".join(fragments[j:j+chunk_size])
                chunks.append({"text": chunk})
            
            # 保存到文件
            with open(output_path, 'w') as f:
                json.dump(chunks, f, indent=2)
        
        print(f"预训练数据处理完成, 耗时: {time.time()-start_time:.2f}秒")
        print(f"预训练数据已保存至: {output_path}")
        return len(chunks)
    
# 处理单个图数据块
def process_chunk(chunk_index, global_ppi, token, data_dir="SFT-Subgraph", output_dir="train_data", input_file = None):
    """
    处理单个数据块并生成数据集
    
    参数:
    chunk_index: 当前处理的数据块索引
    global_ppi: 全局PPI图
    token: TokenIDGene对象
    data_dir: 图数据块所在的目录
    output_dir: 数据集输出目录
    """
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 构建输入文件名（统一使用 dynamic_complex.pkl）
    all_noisy_file = input_file
    
    # 加载数据块
    start_time = time.time()
    print(f"加载 {all_noisy_file} ...")
    with open(all_noisy_file, 'rb') as f:
        all_noisy_subgraphs = pickle.load(f)
    
    # 构建输出文件名
    output_file = os.path.join(output_dir, f"sft_{chunk_index}.json")
    
    print(f"\n处理数据块 #{chunk_index} ...")
    print(f"噪声图数量: {len(all_noisy_subgraphs)}个")
    print(f"加载耗时: {time.time()-start_time:.2f}秒")
    
    # 初始化特征处理器和序列生成器
    feature_processor = GraphFeatureProcessor(global_ppi)
    sequence_generator = GraphSequenceGenerator(token)
    
    # 初始化数据构建器
    data_builder = TrainingDataBuilder(feature_processor, sequence_generator)
    
    # 构建数据集
    print(f"构建预训练数据集...")
    data_builder.build_sft_data(
        all_noisy_subgraphs,
        output_file,
        chunk_size=8  # 每个样本包含8个子图
    )
    
    # 释放内存
    del all_noisy_subgraphs
    gc.collect()
    
    print(f"数据集已保存: {output_file}")
    return output_file

# 主程序
if __name__ == "__main__":
    # 1. 加载全局PPI图
    print("加载全局PPI图...")
    with open('./Graph_init/graph.pkl', 'rb') as f:
        global_ppi = pickle.load(f)
    print(f"全局PPI图加载完成，节点数: {len(global_ppi.nodes())}")
    
    print("导入token...")
    with open('./Graph_init/token_id_gene.pkl', 'rb') as f:
        token_id_gene = pickle.load(f)
    
    # 2. 设置数据目录和输出目录
    data_dir = "Subgraph"          # 存放子图文件的目录
    sft_dir = "finetune_data"           # 输出目录
    os.makedirs(sft_dir, exist_ok=True)
    
    # 3. 处理单个数据块（索引设为0，请根据实际文件名调整）
    input_file = os.path.join(data_dir, f"dynamic_complex.pkl")
    if not os.path.exists(input_file):
        print(f"错误: 数据文件 {input_file} 不存在，请检查路径或修改 chunk_index")
        sys.exit(1)
    
    print(f"\n开始处理数据块 #0 ...")
    sft_file = process_chunk(0, global_ppi, token_id_gene, data_dir, sft_dir, input_file)
    
    print(f"\n处理完成! 数据集保存在: {sft_file}")

