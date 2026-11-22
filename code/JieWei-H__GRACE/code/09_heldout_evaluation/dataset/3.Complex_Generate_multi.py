import pandas as pd
import networkx as nx
import numpy as np
import matplotlib.pyplot as plt
from collections import defaultdict
import warnings
import time
import multiprocessing as mp
from functools import partial
import pickle
import random
from tqdm import tqdm
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# 在类外部定义工作函数，以便pickle
def process_subgraph_worker(args):
    """工作函数，用于并行处理单个子图"""
    original_graph, subgraph, noise_level, num_copies, base_idx = args
    generator = SubgraphGenerator(original_graph)
    noisy_subgraphs_chunk = []
    for j in range(num_copies):
        noisy_graph = generator.add_noise_to_subgraph(subgraph, noise_level)
        noisy_subgraphs_chunk.append((noisy_graph, base_idx))
    return noisy_subgraphs_chunk

class SubgraphGenerator:
    """
    独立子图生成器类，负责从给定的图中生成和处理子图
    
    主要功能：
    1. 从图中生成各种类型的子图
    2. 添加噪声创建变体
    3. 高效存储和加载子图集合
    4. 分析子图统计信息
    """
    
    def __init__(self, original_graph):
        """
        初始化子图生成器
        
        参数:
        original_graph: networkx.Graph - 完整的原始图（用于获取邻居信息）
        """
        self.original_graph = original_graph
    
    def add_noise_to_subgraph(self, subgraph, noise_level=0.5):
        """
        向子图添加节点级别的噪声
        
        参数:
        subgraph: networkx.Graph - 输入子图
        noise_level: float - 噪声水平 (0-1)
        
        返回:
        networkx.Graph - 添加噪声后的子图
        """
        # 创建子图的副本（不修改原始图）
        noisy_graph = subgraph.copy()
        n = noisy_graph.number_of_nodes()
        
        # 2. 节点添加阶段（重点）
        # 计算要添加的节点数（比删除更多）
        max_add = min(
            max(5, n) * 2,  # 添加上限：max(5, 当前节点数)*2
            max(1, int(noise_level * n * 1))  # 基础添加量
        )
        
        # 获取当前子图的节点集合
        current_nodes = set(noisy_graph.nodes())
        
        # 构建邻居候选池
        neighbor_pool = defaultdict(int)
        for node in current_nodes:
            # 获取该节点在原始图中的所有邻居
            neighbors = set(self.original_graph.neighbors(node)) - current_nodes
            for neighbor in neighbors:
                neighbor_pool[neighbor] += 1
        
        # 如果没有候选邻居，直接返回
        if not neighbor_pool:
            return noisy_graph
        
        # 将候选池转换为权重列表
        candidates, weights = zip(*neighbor_pool.items())
        total_weight = sum(weights)
        normalized_weights = [w / total_weight for w in weights]
        
        # 添加新节点
        nodes_added = 0
        while nodes_added < max_add and neighbor_pool:
            # 根据权重随机选择新节点
            new_node = random.choices(candidates, weights=normalized_weights, k=1)[0]
            
            # 添加新节点及其与当前子图的连接
            noisy_graph.add_node(new_node)
            
            # 添加新节点与当前子图的边
            for node in current_nodes:
                if self.original_graph.has_edge(new_node, node):
                    noisy_graph.add_edge(new_node, node)
            
            # 更新当前节点集合
            current_nodes.add(new_node)
            nodes_added += 1
            
            # 更新候选池（移除已添加的节点）
            del neighbor_pool[new_node]
            
            # 添加新节点的邻居到候选池
            new_neighbors = set(self.original_graph.neighbors(new_node)) - current_nodes
            for neighbor in new_neighbors:
                neighbor_pool[neighbor] = neighbor_pool.get(neighbor, 0) + 1
            
            # 重新计算权重
            if neighbor_pool:
                candidates, weights = zip(*neighbor_pool.items())
                total_weight = sum(weights)
                normalized_weights = [w / total_weight for w in weights]
        
        return noisy_graph
    
    def generate_noisy_subgraphs(self, base_subgraphs, target_total_subgraphs=1000000, 
                               num_processes=None, verbose=True, chunksize=20):
        """生成噪声子图集合 - 多进程并行版本"""
        if verbose:
            print("\n开始生成噪声子图集合（多进程并行）...")
            start_time = time.time()
        
        base_labels = {}
        for i, subgraph in enumerate(base_subgraphs):
            base_labels[i] = i

        # 计算权重 - 基于子图大小
        subgraph_weights = []
        for subgraph in base_subgraphs:
            # 获取子图大小（节点数）
            size = subgraph.number_of_nodes()
            # 计算权重：小图权重更高（指数衰减）
            weight = 1.0 / max(1, size**0.5)
            subgraph_weights.append(weight)
        
        # 归一化权重
        total_weight = sum(subgraph_weights)
        subgraph_weights = [w / total_weight for w in subgraph_weights]
        
        # 计算每个基础子图需要生成的噪声副本数量
        copies_per_subgraph = [
            max(1, int(weight * target_total_subgraphs))
            for weight in subgraph_weights
        ]
        # 准备任务参数
        tasks = []
        base_noise = 1  # 基础噪声水平
        for i, (subgraph, num_copies) in enumerate(zip(base_subgraphs, copies_per_subgraph)):
            size = subgraph.number_of_nodes()
            noise_level = base_noise * (10 / max(1, size))**0.5  # 自适应噪声
            tasks.append((self.original_graph, subgraph, noise_level, num_copies, i))
        
        # 确定进程数
        if num_processes is None:
            num_processes = max(1, mp.cpu_count() - 2)  # 保留2个核心给系统
            if verbose:
                print(f"自动选择进程数: {num_processes} (总核心数: {mp.cpu_count()})")
        
        # 使用进程池并行处理
        noisy_subgraphs = []
        graph_label = []
        
        if verbose:
            print(f"使用 {num_processes} 个进程并行处理 {len(tasks)} 个任务...")
        
        with mp.Pool(processes=num_processes) as pool:
            # 使用imap_unordered提高效率
            results = list(tqdm(
                pool.imap_unordered(process_subgraph_worker, tasks, chunksize=chunksize),
                total=len(tasks),
                desc="生成噪声子图"
            ))
        
        # 合并结果
        for chunk in results:
            for graph, label in chunk:
                noisy_subgraphs.append(graph)
                graph_label.append(label)
        
        if verbose:
            elapsed = time.time() - start_time
            print(f"噪声子图生成完成! 共生成 {len(noisy_subgraphs)} 个子图")
            print(f"基础子图: {len(base_subgraphs)}, 噪声子图: {len(noisy_subgraphs)}")
            print(f"总耗时: {elapsed:.2f} 秒")
            
            # 统计节点变化
            base_nodes = sum(sg.number_of_nodes() for sg in base_subgraphs)
            noisy_nodes = sum(sg.number_of_nodes() for sg in noisy_subgraphs)
            if base_nodes > 0:
                print(f"平均节点扩张: {(noisy_nodes/base_nodes - 1)*100:.1f}%")
        
        return noisy_subgraphs, graph_label
      
    @staticmethod
    def save_subgraphs(file_path, subgraphs, format='pkl', verbose=True):
        """
        高效保存子图到文件
        
        参数:
        file_path: str - 文件路径
        subgraphs: list - 子图列表
        format: str - 保存格式 ('pkl', 'json', 'txt')
        verbose: bool - 是否显示进度信息
        """
        if verbose:
            print(f"开始保存子图到 {file_path}...")
            start_time = time.time()
            total_subgraphs = len(subgraphs)
        
        # 根据格式选择保存方法
        if format == 'pkl':
            # 使用pickle二进制格式（最高效）
            with open(file_path, 'wb') as f:
                pickle.dump(subgraphs, f)
        
        elif format == 'json':
            # 使用JSON格式（可读性好，但效率较低）
            import json
            serialized = []
            for i, subgraph in enumerate(subgraphs):
                serialized.append({
                    'nodes': list(subgraph.nodes()),
                    'edges': list(subgraph.edges())
                })
            
            with open(file_path, 'w') as f:
                json.dump(serialized, f)
        
        elif format == 'txt':
            # 使用文本格式（可读性最好）
            with open(file_path, 'w') as f:
                # 写入统计信息
                total_nodes = sum(sg.number_of_nodes() for sg in subgraphs)
                total_edges = sum(sg.number_of_edges() for sg in subgraphs)
                f.write(f"Total Subgraphs: {total_subgraphs}\n")
                f.write(f"Total Nodes: {total_nodes}\n")
                f.write(f"Total Edges: {total_edges}\n\n")
                
                # 分批写入子图数据
                batch_size = 1000
                for i in range(0, len(subgraphs), batch_size):
                    batch = subgraphs[i:i+batch_size]
                    for j, subgraph in enumerate(batch):
                        idx = i + j
                        nodes = sorted(subgraph.nodes())
                        edges = subgraph.edges()
                        f.write(f"Subgraph {idx} - Nodes: {len(nodes)}, Edges: {len(edges)}\n")
                        f.write(f"Nodes: {' '.join(map(str, nodes))}\n")
                        f.write(f"Edges: {' '.join([f'{u}-{v}' for u, v in edges])}\n\n")
        
        else:
            raise ValueError(f"不支持的格式: {format}")
        
        if verbose:
            elapsed = time.time() - start_time
            print(f"已保存 {len(subgraphs)} 个子图到 {file_path}, 耗时 {elapsed:.2f} 秒")
    
    def analyze_subgraphs(self, subgraphs, verbose=True):
        """
        分析子图集合的统计信息
        
        参数:
        subgraphs: list - 子图列表
        verbose: bool - 是否打印结果
        
        返回:
        dict - 包含各种统计信息的字典
        """
        stats = {
            'total_subgraphs': len(subgraphs),
            'total_nodes': sum(sg.number_of_nodes() for sg in subgraphs),
            'total_edges': sum(sg.number_of_edges() for sg in subgraphs),
            'node_counts': [],
            'edge_counts': [],
            'size_distribution': defaultdict(int)
        }
        
        for subgraph in subgraphs:
            node_count = subgraph.number_of_nodes()
            edge_count = subgraph.number_of_edges()
            
            stats['node_counts'].append(node_count)
            stats['edge_counts'].append(edge_count)
            stats['size_distribution'][node_count] += 1
        
        # 计算平均值
        stats['avg_nodes'] = np.mean(stats['node_counts'])
        stats['avg_edges'] = np.mean(stats['edge_counts'])
        
        # 计算标准差
        stats['std_nodes'] = np.std(stats['node_counts'])
        stats['std_edges'] = np.std(stats['edge_counts'])
        
        # 打印结果
        if verbose:
            print("\n子图集合统计信息:")
            print(f"子图总数: {stats['total_subgraphs']}")
            print(f"总节点数: {stats['total_nodes']}")
            print(f"总边数: {stats['total_edges']}")
            print(f"平均节点数: {stats['avg_nodes']:.1f} ± {stats['std_nodes']:.1f}")
            print(f"平均边数: {stats['avg_edges']:.1f} ± {stats['std_edges']:.1f}")
            
            # 打印大小分布
            print("\n子图大小分布:")
            for size, count in sorted(stats['size_distribution'].items()):
                print(f"{size}节点: {count}个子图")
        
        return stats
    
    @staticmethod
    def filter_subgraphs(subgraphs, min_size=1, max_size=50, remove_duplicates=True):
        """
        过滤子图集合
        
        参数:
        subgraphs: list - 输入子图列表
        min_size: int - 最小节点数
        max_size: int - 最大节点数
        remove_duplicates: bool - 是否移除重复子图
        
        返回:
        list - 过滤后的子图列表
        """
        filtered = []
        unique_signatures = set()
        
        for subgraph in subgraphs:
            # 获取节点列表并排序
            nodes = sorted(subgraph.nodes())
            node_count = len(nodes)
            
            # 1. 筛除大小不符合要求的子图
            if node_count < min_size or node_count > max_size:
                continue
            
            # 2. 创建唯一标识（排序后的节点元组）
            signature = tuple(nodes)
            
            # 3. 删除冗余信息（如果启用）
            if remove_duplicates and signature in unique_signatures:
                continue
            
            # 4. 保留包含关系的子图
            filtered.append(subgraph)
            
            # 添加到唯一标识集合
            if remove_duplicates:
                unique_signatures.add(signature)
        
        return filtered

if __name__ == "__main__":
    # 后续加载恢复
    with open('Graph_init/Complex_Train.pkl', 'rb') as f:
        subgraphs = pickle.load(f)
    
    with open('Graph_init/graph.pkl', 'rb') as f:
        graph = pickle.load(f)
    
    generator = SubgraphGenerator(graph)
    
    complex_subgraphs, complex_graph_label = generator.generate_noisy_subgraphs(
        subgraphs, 
        500000,
        num_processes=30,  # 使用所有CPU核心
        chunksize=50  # 根据任务大小调整
    )  # 生成噪声子图
    
    complex_subgraphs = generator.filter_subgraphs(complex_subgraphs)
    
    generator.save_subgraphs("Subgraph/dynamic_complex.pkl", complex_subgraphs)  # 保存
    with open('Subgraph/dynamic_complex_label.pkl', 'wb') as f:
        pickle.dump(complex_graph_label, f)

    generator.analyze_subgraphs(complex_subgraphs)
