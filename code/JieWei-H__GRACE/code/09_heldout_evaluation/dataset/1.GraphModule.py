import pandas as pd
import networkx as nx
import numpy as np
from sklearn.cluster import SpectralClustering
from community import community_louvain
from karateclub import EgoNetSplitter
import matplotlib.pyplot as plt
from collections import defaultdict
import warnings
import time
import cupy as cp
from numba import jit, cuda
import torch
import dgl
import multiprocessing as mp
from functools import partial
from dgl.nn import LabelPropagation
from copy import deepcopy  # 导入深拷贝模块
import pickle

warnings.filterwarnings('ignore')

class PPIClusterAnalyzer:
    def __init__(self, file_path):
        self.file_path = file_path
        self.df = self.load_data()
        
        # 检查GPU可用性
        try:
            self.use_gpu = torch.cuda.is_available()
            print(f"GPU加速 {'可用' if self.use_gpu else '不可用'}，将{'启用' if self.use_gpu else '禁用'}GPU优化")
        except ImportError:
            self.use_gpu = False
            print("PyTorch未安装，禁用GPU优化")
        
        # 创建图并映射节点
        self.graph, self.original_graph, self.node_mapping, self.reverse_mapping = self.create_graph()
        self.all_subgraphs = []
        self.subgraph_counter = 0
        
        self.path_lengths = []
        
        # 图属性统计
        self.n_nodes = self.graph.number_of_nodes()
        self.n_edges = self.graph.number_of_edges()
        self.avg_degree = 2 * self.n_edges / self.n_nodes
        print(f"图统计: {self.n_nodes}节点, {self.n_edges}边, 平均度: {self.avg_degree:.2f}")
    
    def load_data(self):
        """加载PPI数据并预处理"""
        df = pd.read_csv(self.file_path)
        print(f"原始数据包含 {len(df)} 条边")
        return df
    
    def create_graph(self, threshold=None):
        """创建网络图，可选阈值过滤，并确保节点为连续整数"""
        G = nx.Graph()
        node_labels = set()
        
        # 收集所有节点
        for _, row in self.df.iterrows():
            protein1, protein2, _, edge_type = row
            if threshold is None or edge_type == threshold:
                node_labels.add(protein1)
                node_labels.add(protein2)
        
        # 创建映射：原始标签 -> 连续整数
        node_labels = sorted(node_labels)
        node_mapping = {label: idx for idx, label in enumerate(node_labels)}
        reverse_mapping = {idx: label for label, idx in node_mapping.items()}
        
        # 使用映射后的节点创建图
        G_mapped = nx.Graph()
        for _, row in self.df.iterrows():
            protein1, protein2, _, edge_type = row
            if threshold is None or edge_type == threshold:
                mapped1 = node_mapping[protein1]
                mapped2 = node_mapping[protein2]
                G_mapped.add_edge(mapped1, mapped2)
        
        print(f"创建图完成: 节点数={G_mapped.number_of_nodes()}, 边数={G_mapped.number_of_edges()}")
        return G_mapped, G_mapped.copy(), node_mapping, reverse_mapping
    
    def reset_graph(self):
        """重置图为初始状态"""
        self.graph = self.original_graph.copy()
        print("图已重置为初始状态")
        
    def get_graph(self):
        G = self.original_graph
        return G
    
    def _format_clusters(self, partition):
        """格式化聚类结果为字典"""
        clusters = defaultdict(list)
        for node, cluster_id in partition.items():
            clusters[cluster_id].append(node)
        community_sizes = {cid: len(nodes) for cid, nodes in clusters.items()}
        print(len(community_sizes))
        #print("每个社区的节点数量:", community_sizes)
        return dict(clusters)
      
    def spectral_clustering(self, n_clusters=1000):
        """谱聚类算法 - GPU优化版本"""
        adj_matrix = nx.to_numpy_array(self.graph)
        self.use_gpu = False
        
        if self.use_gpu:
            try:
                # 使用RAPIDS cuML进行GPU加速谱聚类
                from cuml import SpectralClustering as cuSpectralClustering
                sc = cuSpectralClustering(
                    n_clusters=n_clusters,
                    affinity='precomputed',
                    random_state=42
                )
                labels = sc.fit_predict(adj_matrix)
                print(" [谱聚类] 使用cuML (GPU)")
            except ImportError:
                print("cuML不可用，回退到CPU实现")
                from sklearn.cluster import SpectralClustering
                sc = SpectralClustering(
                    n_clusters=n_clusters,
                    affinity='precomputed',
                    assign_labels='discretize',
                    random_state=42
                )
                labels = sc.fit_predict(adj_matrix)
        else:
            from sklearn.cluster import SpectralClustering
            sc = SpectralClustering(
                n_clusters=n_clusters,
                affinity='precomputed',
                assign_labels='discretize',
                random_state=42
            )
            labels = sc.fit_predict(adj_matrix)
        
        nodes = list(self.graph.nodes())
        partition = {nodes[i]: labels[i] for i in range(len(nodes))}
        return self._format_clusters(partition)
    
    def ego_network_clustering(self, n_clusters=1000):
        """Ego网络分割算法 - 并行优化"""
        model = EgoNetSplitter(n_clusters/30)
        model.fit(self.graph)
        membership = model.get_memberships()
        partition = {node: cluster_id[0] for node, cluster_id in membership.items()}
        # for node, cluster_id in membership.items():
        #     count = len(cluster_id)
        #     if count > 1:
        #         print(f"节点 {node} 的聚类包含 {count} 个元素: {cluster_id}")
        return self._format_clusters(partition)
    
    def label_propagation_clustering(self, n_clusters=1000):
        """标签传播算法 - GPU优化版本"""
        if self.use_gpu:
            try:
                # 创建DGL图并转移到GPU
                g = dgl.from_networkx(self.graph)
                g = g.to('cuda:0')
                n_nodes = self.graph.number_of_nodes()
                
                # 初始化标签：每个节点分配唯一ID（0到n-1）
                labels_init = torch.randint(0, n_clusters, (n_nodes,), device='cuda:0')
                
                # 创建标签传播实例并运行
                lp = LabelPropagation(k=50, alpha=0.8)
                label_probabilities = lp(g, labels_init)  # 形状为 [n_nodes, n_classes]
            
                # 将概率分布转换为硬簇分配（选择概率最大的类）
                hard_labels = torch.argmax(label_probabilities, dim=1)
                
                # 将标签映射回原始节点
                partition = {
                    node: hard_labels[i].item() 
                    for i, node in enumerate(self.graph.nodes())
                }
                return self._format_clusters(partition)
            except Exception as e:
                print(f"GPU标签传播失败: {e}, 回退到CPU实现")
        
        # CPU实现
        clusters = {}
        partition = nx.algorithms.community.label_propagation_communities(self.graph)
        for i, community in enumerate(partition):
            clusters[i] = list(community)
        return clusters
    
    def _compute_distances_numba(self, path_lengths, dist_matrix, nodes, node_index):
        """使用Numba加速距离矩阵计算"""
        n = len(nodes)
        for i in range(n):
            u = nodes[i]
            for j in range(n):
                v = nodes[j]
                if i == j:
                    dist_matrix[i, j] = 0
                else:
                    if v in path_lengths[u]:
                        dist_matrix[i, j] = path_lengths[u][v]
                    else:
                        dist_matrix[i, j] = 1e9  # 不可达节点
        return dist_matrix
    
    def hierarchical_clustering(self, n_clusters=1000, linkage='average'):
        """层次聚类算法 - GPU优化版本"""
        self.use_gpu = False
        if self.use_gpu:
            try:
                # 使用RAPIDS cuML进行GPU加速层次聚类
                from cuml import AgglomerativeClustering as cuAgglomerativeClustering
                
                # 计算距离矩阵
                # path_lengths = dict(nx.all_pairs_shortest_path_length(self.graph))
                nodes = list(self.graph.nodes())
                n = len(nodes)
                
                # 使用Numba加速距离矩阵计算
                dist_matrix = np.zeros((n, n))
                node_index = {node: idx for idx, node in enumerate(nodes)}
                dist_matrix = self._compute_distances_numba(path_lengths, dist_matrix, nodes, node_index)
                
                # GPU聚类
                model = cuAgglomerativeClustering(
                    n_clusters=n_clusters,
                    affinity='precomputed',
                    linkage=linkage,
                    metric='precomputed'
                )
                model.fit(dist_matrix)
                labels = model.labels_
                print("  [层次聚类] 使用cuML (GPU)")
                partition = {node: labels[node_index[node]] for node in nodes}
                return self._format_clusters(partition)
            except ImportError:
                print("cuML不可用，回退到CPU实现")
        
        # CPU实现
        # path_lengths = dict(nx.all_pairs_shortest_path_length(analyzer.graph))
        dist_matrix = np.zeros((len(analyzer.graph.nodes()), len(analyzer.graph.nodes())))
        
        nodes = list(self.graph.nodes())
        node_index = {node: idx for idx, node in enumerate(nodes)}
        
        # 使用Numba加速距离矩阵计算
        dist_matrix = self._compute_distances_numba(self.path_lengths, dist_matrix, nodes, node_index)
        
        from sklearn.cluster import AgglomerativeClustering
        model = AgglomerativeClustering(
            n_clusters=n_clusters,
            linkage=linkage,
            metric='precomputed'
        )
        model.fit(dist_matrix)
        
        partition = {node: model.labels_[node_index[node]] for node in nodes}
        return self._format_clusters(partition)
    
    def generate_all_subgraphs_parallel(self, methods_params, verbose=False):
        """使用所有聚类方法生成子图，并进行过滤优化"""
        self.all_subgraphs = []
        if verbose:
            self.path_lengths = dict(nx.all_pairs_shortest_path_length(self.graph))
        
        print("开始顺序执行所有聚类方法生成子图并进行过滤...")
        start_time = time.time()  # 记录开始时间
        print(f"共有 {len(methods_params)} 个方法需要执行")
        
        unique_clusters = set()  # 用于存储唯一聚类标识
        
        # 遍历所有聚类方法 - 顺序执行
        for i, (method, params) in enumerate(methods_params):
            print(f"\n===== 开始执行方法 {i+1}/{len(methods_params)}: {method} =====")
            print(f"参数: {params}")
            
            try:
                # 直接调用聚类方法
                clusters = self._generate_subgraphs_for_method(method, params)
                print(f"{method} 聚类完成，生成 {len(clusters)} 个簇")
                
                # 处理聚类结果
                cluster_count = 0
                for cluster_id, nodes in clusters.items():
                    if len(nodes) == 1:
                        continue
                    
                    # 2. 一个结点的聚类依然保留
                    # 3. 删除冗余信息（完全相同的聚类）
                    node_tuple = tuple(sorted(nodes))
                    
                    if node_tuple in unique_clusters:
                        continue
                    
                    # 4. 保留包含关系的聚类
                    unique_clusters.add(node_tuple)
                    
                    # 创建子图
                    subgraph = self.graph.subgraph(nodes)
                    self.all_subgraphs.append(subgraph)
                    cluster_count += 1
                    self.subgraph_counter += 1
                
                print(f"{method} 添加了 {cluster_count} 个有效子图")
            
            except Exception as e:
                print(f"!!! {method} 聚类失败: {str(e)}")
                import traceback
                traceback.print_exc()  # 打印完整错误堆栈
        
        elapsed = time.time() - start_time
        print(f"\n===== 子图生成完成! =====")
        print(f"共生成 {len(self.all_subgraphs)} 个子图")
        print(f"总耗时: {elapsed:.2f} 秒")
        return self.all_subgraphs
  
    def _generate_subgraphs_for_method(self, method, params):
        """为单个聚类方法生成子图（包含基本错误处理）"""
        try:
            # 调用聚类方法获取结果
            clusters = self.analyze_clusters(method, **params)
            return clusters
        except Exception as e:
            # 处理异常情况
            print(f"  {method.upper()} 聚类失败: {str(e)}")
            return {}  # 返回空字典
          
    def analyze_clusters(self, method, **kwargs):
        """执行聚类分析并返回结果"""
        method = method.lower()
        if method == 'spectral':
            return self.spectral_clustering(**kwargs)
        elif method == 'ego':
            return self.ego_network_clustering(**kwargs)
        elif method == 'labelprop':
            return self.label_propagation_clustering(**kwargs)
        elif method == 'hierarchical':
            return self.hierarchical_clustering(**kwargs)
        else:
            raise ValueError(f"未知的聚类方法: {method}")
    
    def load_complex_subgraphs(self, complex_csv_path, output_dir=None, verbose=True):
        """
        加载复合物数据并转化为子图格式（仅基于节点）
        
        参数:
        complex_csv_path: str - 复合物数据CSV文件路径
        output_dir: str - 输出目录（可选）
        verbose: bool - 是否显示进度信息
        
        返回:
        list - 子图列表
        """
        if verbose:
            print(f"\n开始处理复合物数据: {complex_csv_path}")
            start_time = time.time()
        
        # 读取复合物CSV文件
        complex_df = pd.read_csv(complex_csv_path)
        
        if verbose:
            print(f"读取完成: 共 {len(complex_df)} 条记录")
        
        # 按复合物名称分组并收集所有唯一节点
        complex_nodes = defaultdict(set)
        for _, row in complex_df.iterrows():
            complex_name = row['Names']
            protein1 = row['protein1']
            protein2 = row['protein2']
            
            # 添加到复合物节点集合
            complex_nodes[complex_name].add(protein1)
            complex_nodes[complex_name].add(protein2)
        
        if verbose:
            print(f"发现 {len(complex_nodes)} 个复合物")
        
        # 创建复合物子图（使用映射后的节点）
        subgraphs = []
        metadata = []  # 存储元数据的列表
        for complex_name, protein_set in complex_nodes.items():
            # 映射蛋白质名称到图节点ID
            mapped_nodes = set()
            for protein in protein_set:
                mapped_node = self.node_mapping.get(protein)
                if mapped_node is not None:
                    mapped_nodes.add(mapped_node)
            
            # 跳过空复合物
            if not mapped_nodes:
                continue
            
            # 创建子图（仅包含节点）
            subgraph = self.graph.subgraph(mapped_nodes)  
            
            # 添加复合物元数据
            # subgraph.graph['name'] = str(complex_name)
            # subgraph.graph['type'] = 'complex'
            # subgraph.graph['original_nodes'] = [self.reverse_mapping[n] for n in mapped_nodes]
            
            # 存储元数据而非修改子图
            # print(str(complex_name))
            metadata.append(str(complex_name))
            
            subgraphs.append(subgraph)
        
        if verbose:
            elapsed = time.time() - start_time
            print(f"成功创建 {len(subgraphs)} 个子图, 耗时: {elapsed:.2f}秒")
        
        # 保存结果（如果需要）
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            graph_data = []
            for i, subgraph in enumerate(subgraphs):
                nodes = sorted(subgraph.nodes())
                graph_data.append({
                    'complex_id': i,
                    'complex_name': subgraph.graph['name'],
                    'nodes': ';'.join(map(str, nodes)),
                    'original_nodes': ';'.join(subgraph.graph['original_nodes']),
                    'size': len(nodes)
                })
            
            graph_df = pd.DataFrame(graph_data)
            graph_path = os.path.join(output_dir, "complex_subgraphs.csv")
            graph_df.to_csv(graph_path, index=False)
            
            if verbose:
                print(f"结果已保存到: {output_dir}")
        
        metadata =  {f"{i}": name for i, name in enumerate(metadata)}
        
        return subgraphs, metadata
      
    @staticmethod
    def filter_subgraphs(subgraphs, min_size=1, max_size=30, remove_duplicates=True):
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
              
if __name__ == "__main__":
    # 生成主图
    analyzer = PPIClusterAnalyzer("../../../GraphData/final_ppi_network.csv")
    token_id_gene = TokenIDGene()
    token_id_gene.gene_to_id = analyzer.node_mapping
    token_id_gene.id_to_gene = analyzer.reverse_mapping
    
    gene_names = list(token_id_gene.gene_to_id.keys())
    torch.save(gene_names, 'gene_names.pt')
    
    with open('Graph_init/Complex_Train.pkl', 'rb') as f:
        complex_graphs = pickle.load(f)
        
    with open('Graph_init/token_id_gene.pkl', 'wb') as f:
        pickle.dump(token_id_gene, f)
        
    graph = analyzer.get_graph()
    
    with open('Graph_init/graph.pkl', 'wb') as f:
        pickle.dump(graph, f)
    
    methods_params1 = [
            ('ego', {'n_clusters': 1000}),       # Ego网络聚类
            ('ego', {'n_clusters': 2000}),
            ('ego', {'n_clusters': 3000}),
            ('ego', {'n_clusters': 4000}),
            ('ego', {'n_clusters': 5000})
    ]
    EGO_graphs = analyzer.generate_all_subgraphs_parallel(methods_params1)
    
    # methods_params2 = [
    #         ('spectral', {'n_clusters': 1000}), # 标签传播聚类
    #         ('spectral', {'n_clusters': 2000}),
    #         ('spectral', {'n_clusters': 3000}),
    #         ('spectral', {'n_clusters': 4000}),
    #         ('spectral', {'n_clusters': 5000}),
    # ]
    # Specctral_graphs = analyzer.generate_all_subgraphs_parallel(methods_params2)
    # with open('Specctral_graphs.pkl', 'wb') as f:
    #     pickle.dump(Specctral_graphs, f)
        
    with open('./Graph_init/Specctral_graphs.pkl', 'rb') as f:
        Specctral_graphs = pickle.load(f)
    
    methods_params3 = [
            ('labelprop', {'n_clusters': 1000}), # 标签传播聚类
            ('labelprop', {'n_clusters': 2000}),
            ('labelprop', {'n_clusters': 3000}),
            ('labelprop', {'n_clusters': 4000}),
            ('labelprop', {'n_clusters': 5000}),
    ]
    Labelprop_graphs = analyzer.generate_all_subgraphs_parallel(methods_params3)
    
    methods_params4 = [
            ('hierarchical', {'n_clusters': 1000}), # 层次聚类
            ('hierarchical', {'n_clusters': 2000}),
            ('hierarchical', {'n_clusters': 3000}),
            ('hierarchical', {'n_clusters': 4000}),
            ('hierarchical', {'n_clusters': 5000}),
    ]
    Hierarchical_graphs = analyzer.generate_all_subgraphs_parallel(methods_params4, True)
    
    all_subgraphs = complex_graphs + EGO_graphs + Labelprop_graphs + Hierarchical_graphs + Specctral_graphs
    
    filt_subgraphs = analyzer.filter_subgraphs(all_subgraphs)
    # 保存 all_subgraph和Graph 到文件
    with open('./Graph_init/all_subgraphs.pkl', 'wb') as f:
        pickle.dump(filt_subgraphs, f)
