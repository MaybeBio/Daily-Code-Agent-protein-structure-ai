import pandas as pd
import networkx as nx
import numpy as np
import matplotlib.pyplot as plt
from collections import defaultdict
import pickle
import time

class HubNodeAnalyzer:
    def __init__(self, graph, node_mapping, reverse_mapping):
        """
        初始化Hub节点分析器
        
        参数:
        graph: networkx图对象
        node_mapping: 节点映射字典
        reverse_mapping: 反向映射字典
        """
        self.graph = graph
        self.node_mapping = node_mapping
        self.reverse_mapping = reverse_mapping
        self.n_nodes = graph.number_of_nodes()
    
    def calculate_centrality_measures(self, use_sampling=True, sample_size=1000):
        """快速计算中心性指标 - 优化版本"""
        print("开始快速计算中心性指标...")
        start_time = time.time()
        
        centrality_scores = {}
        
        # 1. 度中心性 (最快)
        print("1. 计算度中心性...")
        degree_start = time.time()
        centrality_scores['degree'] = nx.degree_centrality(self.graph)
        centrality_scores['actual_degree'] = dict(self.graph.degree())
        print(f"   度中心性计算完成: {time.time()-degree_start:.2f}秒")
        
        # 2. 特征向量中心性 (中等速度)
        print("2. 计算特征向量中心性...")
        eigen_start = time.time()
        try:
            centrality_scores['eigenvector'] = nx.eigenvector_centrality(
                self.graph, max_iter=500, tol=1e-4
            )
        except:
            print("   特征向量中心性计算失败，使用度中心性替代")
            centrality_scores['eigenvector'] = centrality_scores['degree'].copy()
        print(f"   特征向量中心性计算完成: {time.time()-eigen_start:.2f}秒")
        
        # 3. 介数中心性 - 使用近似算法
        print("3. 计算近似介数中心性...")
        betweenness_start = time.time()
        
        if use_sampling and self.n_nodes > 5000:
            # 对于大图使用采样方法
            k = min(sample_size, self.n_nodes // 10)
            centrality_scores['betweenness'] = nx.betweenness_centrality(
                self.graph, k=k, normalized=True, seed=42
            )
            print(f"   使用{k}个样本进行近似介数中心性计算")
        else:
            # 对于小图使用精确计算
            centrality_scores['betweenness'] = nx.betweenness_centrality(
                self.graph, normalized=True
            )
        
        print(f"   介数中心性计算完成: {time.time()-betweenness_start:.2f}秒")
        
        # 跳过接近中心性 - 计算成本太高
        centrality_scores['closeness'] = centrality_scores['degree'].copy()
        
        total_time = time.time() - start_time
        print(f"所有中心性指标计算完成，总耗时: {total_time:.2f}秒")
        
        return centrality_scores
    
    def identify_hub_nodes(self, top_percent=10, centrality_scores = None):
        """
        识别hub节点
        
        参数:
        top_percent: 前百分之几的节点被认为是候选hub
        min_criteria: 至少满足几个标准才能被认定为hub节点
        
        返回:
        hub_nodes: hub节点列表
        centrality_scores: 所有节点的中心性分数
        """
        
        # 确定阈值（前top_percent%）
        threshold_idx = int(self.n_nodes * top_percent / 100)
        
        # 为每个指标打分
        node_scores = defaultdict(float)
        
        # 度中心性分数 (权重0.5)
        sorted_degree = sorted(centrality_scores['degree'].items(), 
                             key=lambda x: x[1], reverse=True)
        for rank, (node, score) in enumerate(sorted_degree):
            node_scores[node] += (1 - rank/self.n_nodes) * 0.5
        
        # 特征向量中心性分数 (权重0.3)
        sorted_eigen = sorted(centrality_scores['eigenvector'].items(), 
                            key=lambda x: x[1], reverse=True)
        for rank, (node, score) in enumerate(sorted_eigen):
            node_scores[node] += (1 - rank/self.n_nodes) * 0.3
        
        # 介数中心性分数 (权重0.2)
        sorted_between = sorted(centrality_scores['betweenness'].items(), 
                              key=lambda x: x[1], reverse=True)
        for rank, (node, score) in enumerate(sorted_between):
            node_scores[node] += (1 - rank/self.n_nodes) * 0.2
        
        # 按综合分数排序
        sorted_nodes = sorted(node_scores.items(), key=lambda x: x[1], reverse=True)
        hub_nodes = [node for node, score in sorted_nodes[:threshold_idx]]
        
        print(f"\nHub节点识别完成")
        
        return hub_nodes
    
    def get_hub_node_details(self, hub_nodes, centrality_scores):
        """获取hub节点的详细信息"""
        hub_details = []
        
        for node in hub_nodes:
            original_name = self.reverse_mapping[node]
            hub_details.append({
                'node_id': node,
                'protein_name': original_name,
                'degree': centrality_scores['actual_degree'][node],
                'degree_centrality': centrality_scores['degree'][node],
                'betweenness_centrality': centrality_scores['betweenness'][node],
                'eigenvector_centrality': centrality_scores['eigenvector'][node]
            })
        
        # 按度中心性排序
        hub_details.sort(key=lambda x: x['degree_centrality'], reverse=True)
        
        return hub_details
    
    def save_hub_nodes(self, hub_details, output_path):
        """保存hub节点信息到文件"""
        df = pd.DataFrame(hub_details)
        df.to_csv(output_path, index=False)
        print(f"Hub节点信息已保存到: {output_path}")
        
        # 同时保存pickle格式便于后续使用
        with open(output_path.replace('.csv', '.pkl'), 'wb') as f:
            pickle.dump(hub_details, f)
        print(f"Hub节点pickle文件已保存")
    
    def visualize_top_hubs(self, hub_details, top_n=20):
        """可视化前top_n个hub节点"""
        
        # 设置全局字体为 Times New Roman
        plt.rcParams['font.family'] = 'Times New Roman'
        # 可选的额外设置，提高清晰度
        plt.rcParams['mathtext.fontset'] = 'stix'  # 数学公式也用Times风格
        
        top_hubs = hub_details[:top_n]
        
        fig, axes = plt.subplots(2, 2, figsize=(8.5, 6))
        fig.suptitle(f'Top {top_n} Hub Analyse', fontsize=16, fontname='Times New Roman')
        
        # 度分布
        degrees = [hub['degree'] for hub in top_hubs]
        names = [hub['protein_name'] for hub in top_hubs]
        axes[0,0].bar(range(len(degrees)), degrees)
        axes[0,0].set_title('Node degree distribution', fontname='Times New Roman')
        axes[0,0].set_ylabel('Degree', fontname='Times New Roman')
        axes[0,0].set_xticks(range(len(names)))
        axes[0,0].set_xticklabels(names, rotation=45, ha='right', fontname='Times New Roman')
        
        # 设置所有子图的字体
        for ax in axes.flat:
            ax.title.set_fontname('Times New Roman')
            ax.xaxis.label.set_fontname('Times New Roman')
            ax.yaxis.label.set_fontname('Times New Roman')
            
            # 设置刻度标签字体
            for label in ax.get_xticklabels():
                label.set_fontname('Times New Roman')
            for label in ax.get_yticklabels():
                label.set_fontname('Times New Roman')
        
        # 中心性指标比较
        metrics = ['degree_centrality', 'betweenness_centrality', 'eigenvector_centrality']
        metric_names = ['Degree Centrality', 'Betweenness Centrality', 'Eigenvector Centrality']
        
        x = np.arange(len(top_hubs))
        width = 0.2
        
        for i, metric in enumerate(metrics):
            values = [hub[metric] for hub in top_hubs]
            axes[0,1].bar(x + i*width, values, width, label=metric_names[i])
        
        axes[0,1].set_title('Comparison of Centrality Metrics', fontname='Times New Roman')
        axes[0,1].set_ylabel('Centrality', fontname='Times New Roman')
        axes[0,1].set_xticks(x + width*1.5)
        axes[0,1].set_xticklabels(names, rotation=45, ha='right', fontname='Times New Roman')
        legend = axes[0,1].legend()
        for text in legend.get_texts():
            text.set_fontname('Times New Roman')
        
        # 中心性指标散点图
        degree_vals = [hub['degree_centrality'] for hub in top_hubs]
        betweenness_vals = [hub['betweenness_centrality'] for hub in top_hubs]
        axes[1,0].scatter(degree_vals, betweenness_vals, alpha=0.6)
        for i, name in enumerate(names):
            axes[1,0].annotate(name, (degree_vals[i], betweenness_vals[i]), 
                             xytext=(5, 5), textcoords='offset points', 
                             fontsize=8, fontname='Times New Roman')
        axes[1,0].set_xlabel('Degree Centrality', fontname='Times New Roman')
        axes[1,0].set_ylabel('Betweenness Centrality', fontname='Times New Roman')
        axes[1,0].set_title('Degree Centrality vs Betweenness Centrality', fontname='Times New Roman')
        
        # 节点重要性排名
        ranks = range(1, len(top_hubs) + 1)
        degree_scores = [hub['degree_centrality'] for hub in top_hubs]
        axes[1,1].plot(ranks, degree_scores, 'o-', label='Degree Centrality')
        eigen_scores = [hub['eigenvector_centrality'] for hub in top_hubs]
        axes[1,1].plot(ranks, eigen_scores, 's-', label='Eigenvector Centrality')
        axes[1,1].set_xlabel('Rank', fontname='Times New Roman')
        axes[1,1].set_ylabel('Centrality', fontname='Times New Roman')
        axes[1,1].set_title('Hub Nodes', fontname='Times New Roman')
        legend2 = axes[1,1].legend()
        for text in legend2.get_texts():
            text.set_fontname('Times New Roman')
        axes[1,1].invert_xaxis()
        
        plt.tight_layout()
        plt.savefig('hub_nodes_analysis.png', dpi=300, bbox_inches='tight')
        plt.show()

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

def main():
    """主函数：加载图数据并识别hub节点"""
    # 加载之前保存的图数据
    try:
        with open('../Graph_init/graph.pkl', 'rb') as f:
            graph = pickle.load(f)
        with open('../Graph_init/token_id_gene.pkl', 'rb') as f:
            token_id_gene = pickle.load(f)
        
        print("图数据加载成功")
        print(f"节点数: {graph.number_of_nodes()}")
        print(f"边数: {graph.number_of_edges()}")
        
    except FileNotFoundError:
        print("找不到图数据文件，请先运行GraphModule.py生成图数据")
        return
    
    # 创建hub节点分析器
    analyzer = HubNodeAnalyzer(
        graph=graph,
        node_mapping=token_id_gene.gene_to_id,
        reverse_mapping=token_id_gene.id_to_gene
    )
    
    # 计算中心性指标
    centrality_scores = analyzer.calculate_centrality_measures()
    
    with open('../Graph_init/centrality_scores.pkl', 'wb') as f:
        pickle.dump(centrality_scores, f)
    

    percentages = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    hub_node_ids = {}
    
    for p in percentages:
        # 识别hub节点
        hub_nodes = analyzer.identify_hub_nodes(
            top_percent=p,  # 前5%
            centrality_scores = centrality_scores,
        )
        # 获取详细信息
        hub_details = analyzer.get_hub_node_details(hub_nodes, centrality_scores)
        hub_node_ids[p] = [hub['protein_name'] for hub in hub_details]
    
    
    # 打印前20个hub节点
    print("\n前20个最重要的Hub节点:")
    print("=" * 100)
    print(f"{'排名':<4} {'蛋白名称':<15} {'度':<6} {'度中心性':<10} {'介数中心性':<12} {'特征向量中心性':<12}")
    print("-" * 100)
    
    for i, hub in enumerate(hub_details[:20], 1):
        print(f"{i:<4} {hub['protein_name']:<15} {hub['degree']:<6} "
              f"{hub['degree_centrality']:<10.4f} {hub['betweenness_centrality']:<12.4f} "
              f"{hub['eigenvector_centrality']:<12.4f}")
    
    # 保存结果
    # analyzer.save_hub_nodes(hub_details, 'hub_nodes_detailed.csv')
    
    # 可视化
    analyzer.visualize_top_hubs(hub_details, top_n=20)
    
    # 统计信息
    print(f"\nHub节点统计:")
    print(f"总hub节点数: {len(hub_details)}")
    print(f"平均度: {np.mean([h['degree'] for h in hub_details]):.2f}")
    print(f"最大度: {max([h['degree'] for h in hub_details])}")
    print(f"最小度: {min([h['degree'] for h in hub_details])}")
    
    # 保存简化的hub节点列表（仅节点ID）
    
    with open('hub_nodes_ids.pkl', 'wb') as f:
        pickle.dump(hub_node_ids, f)
    print(f"Hub节点ID列表已保存到: hub_nodes_ids.pkl")
