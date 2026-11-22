import pickle
import numpy as np
import networkx as nx
import glob
import os
import pandas as pd
import random

def load_complex_sets(pkl_file, id_to_gene):
    """
    从pkl文件加载已知复合物子图，将每个子图的整数节点ID转换为蛋白质名称字符串集合。
    id_to_gene: 字典 {节点ID: 蛋白质名称}
    """
    with open(pkl_file, 'rb') as f:
        subgraphs = pickle.load(f)
    sets = []
    for sg in subgraphs:
        node_ids = set(sg.nodes())
        protein_names = {id_to_gene[nid] for nid in node_ids if nid in id_to_gene}
        sets.append(protein_names)
    return sets

def load_pred_set(pkl_file):
    """从pkl文件加载预测结果，返回每个复合物的节点集合（Python set），从'sft_response'字段提取"""
    with open(pkl_file, 'rb') as f:
        subgraphs = pickle.load(f)
    sets = [set(sg['sft_response'].split()) for sg in subgraphs]
    
    # 转换为 DataFrame（每个复合物一行，蛋白质名称用逗号分隔）
    data = {'complex_id': [f'complex_{i}' for i in range(len(sets))],
            'proteins': [','.join(sorted(c)) for c in sets]}
    df = pd.DataFrame(data)
    
    pkl_file = pkl_file.replace(".pkl", ".csv")
    # 保存为 CSV
    df.to_csv(f'{pkl_file}', index=False)
    
    return sets

def compute_mmr(set_a, set_b):
    """计算两个集合的最大匹配率 (|A∩B|^2)/(|A|*|B|)"""
    intersection = len(set_a & set_b)
    return (intersection ** 2) / (len(set_a) * len(set_b)) if len(set_a) and len(set_b) else 0.0

def greedy_matching(known_sets, pred_sets, threshold=0.2):
    """
    基于MMR阈值进行贪心一对一匹配
    返回: matches (list of (known_idx, pred_idx, mmr))
    """
    candidates = []
    for ki, kset in enumerate(known_sets):
        for pi, pset in enumerate(pred_sets):
            mmr = compute_mmr(kset, pset)
            if mmr > threshold:
                candidates.append((mmr, ki, pi))
    candidates.sort(reverse=True, key=lambda x: x[0])

    matched_known = set()
    matched_pred = set()
    matches = []
    for mmr, ki, pi in candidates:
        if ki not in matched_known and pi not in matched_pred:
            matches.append((ki, pi, mmr))
            matched_known.add(ki)
            matched_pred.add(pi)
    return matches

def compute_global_mmr(known_sets, pred_sets):
    """
    计算全局MMR = (最大权匹配的总权重) / 已知复合物数量
    优先使用SciPy的匈牙利算法，若不可用则使用贪心近似。
    """
    n_known = len(known_sets)
    n_pred = len(pred_sets)
    if n_known == 0 or n_pred == 0:
        return 0.0

    weights = np.zeros((n_known, n_pred))
    for i, ks in enumerate(known_sets):
        for j, ps in enumerate(pred_sets):
            weights[i, j] = compute_mmr(ks, ps)

    try:
        from scipy.optimize import linear_sum_assignment
        row_ind, col_ind = linear_sum_assignment(-weights)  # 最大化权重
        total_weight = weights[row_ind, col_ind].sum()
    except ImportError:
        print("警告: scipy未安装，使用贪心近似计算全局MMR，可能与真实最大匹配有偏差。")
        candidates = []
        for i in range(n_known):
            for j in range(n_pred):
                candidates.append((weights[i, j], i, j))
        candidates.sort(reverse=True, key=lambda x: x[0])
        matched_known = set()
        matched_pred = set()
        total_weight = 0.0
        for w, i, j in candidates:
            if i not in matched_known and j not in matched_pred:
                total_weight += w
                matched_known.add(i)
                matched_pred.add(j)

    return total_weight / n_known

def evaluate(known_sets, pred_sets, threshold=0.2):
    """
    计算统计信息和评估指标
    返回包含以下指标的字典：
      - 基本统计量
      - 图片定义的Precision, Recall, F1, 全局MMR
      - 原代码保留的平均匹配率Mean_MMR（基于贪心匹配）
    """
    n_known = len(known_sets)
    n_pred = len(pred_sets)

    # 大小统计
    known_sizes = [len(s) for s in known_sets]
    pred_sizes = [len(s) for s in pred_sets]
    stats = {
        'num_known_complexes': n_known,
        'num_pred_complexes': n_pred,
        'known_size_min': min(known_sizes) if known_sizes else 0,
        'known_size_max': max(known_sizes) if known_sizes else 0,
        'known_size_avg': np.mean(known_sizes) if known_sizes else 0,
        'pred_size_min': min(pred_sizes) if pred_sizes else 0,
        'pred_size_max': max(pred_sizes) if pred_sizes else 0,
        'pred_size_avg': np.mean(pred_sizes) if pred_sizes else 0,
    }

    # 预先计算所有MMR
    mmr_matrix = np.zeros((n_known, n_pred))
    for i, ks in enumerate(known_sets):
        for j, ps in enumerate(pred_sets):
            mmr_matrix[i, j] = compute_mmr(ks, ps)

    # ----- 图片定义的指标（基于简单阈值匹配）-----
    P_gc = 0  # 匹配上的预测复合物数
    G_pc = 0  # 匹配上的已知复合物数
    for j in range(n_pred):
        if any(mmr_matrix[i, j] >= threshold for i in range(n_known)):
            P_gc += 1
    for i in range(n_known):
        if any(mmr_matrix[i, j] >= threshold for j in range(n_pred)):
            G_pc += 1

    precision = P_gc / n_pred if n_pred > 0 else 0.0
    recall = G_pc / n_known if n_known > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # 全局MMR（基于最大匹配）
    global_mmr = compute_global_mmr(known_sets, pred_sets)

    # ----- 保留原代码中的平均匹配率（基于贪心一对一匹配）-----
    greedy_matches = greedy_matching(known_sets, pred_sets, threshold)
    mean_mmr_greedy = np.mean([mmr for _, _, mmr in greedy_matches]) if greedy_matches else 0.0

    metrics = {
        # 图片定义指标
        'P_gc': P_gc,
        'G_pc': G_pc,
        'Precision': precision,
        'Recall': recall,
        'F1': f1,
        'Global_MMR': global_mmr,
        # 保留的平均匹配率
        'Mean_MMR': mean_mmr_greedy,
    }

    return {**stats, **metrics}


def print_results(results):
    """格式化打印结果"""
    print("\n========== 复合物预测评估结果 ==========")
    print(f"已知复合物数量: {results['num_known_complexes']}")
    print(f"预测复合物数量: {results['num_pred_complexes']}")
    print(f"已知复合物大小: 最小={results['known_size_min']}, 最大={results['known_size_max']}, 平均={results['known_size_avg']:.2f}")
    print(f"预测复合物大小: 最小={results['pred_size_min']}, 最大={results['pred_size_max']}, 平均={results['pred_size_avg']:.2f}")

    print("\n----- 图片定义指标（简单阈值匹配）-----")
    print(f"P_gc (匹配上的预测复合物数) = {results['P_gc']}")
    print(f"G_pc (匹配上的已知复合物数) = {results['G_pc']}")
    print(f"Precision = {results['Precision']:.4f}")
    print(f"Recall    = {results['Recall']:.4f}")
    print(f"F1        = {results['F1']:.4f}")
    print(f"Global MMR (最大匹配总权重 / 已知复合物数) = {results['Global_MMR']:.4f}")
    print(f"Mean_MMR (匹配上的复合物对MMR均值) = {results['Mean_MMR']:.4f}")
    print("=========================================\n")

class TokenIDGene:
    def __init__(self):
        self.gene_to_id = {}
        self.id_to_gene = {}

    def add_mapping(self, gene, id):
        self.gene_to_id[gene] = id
        self.id_to_gene[id] = gene

    def get_id(self, gene):
        return self.gene_to_id.get(gene)

    def get_gene(self, id):
        return self.id_to_gene.get(id)
      
if __name__ == "__main__":
    # 文件路径（请根据实际情况修改）
    mapping_file = "token_id_gene.pkl"
    with open(mapping_file, 'rb') as f:
        token_id_gene = pickle.load(f)
    id_to_gene = token_id_gene.id_to_gene
    
    results_list = []
    
    
    known_file = "../Graph_init/complex_graphs.pkl"   # 已知复合物子图文件（节点为整数ID）
    
    for i in range(4):
        pred_file  = f"generation_results-{i+1}.pkl"      # 预测结果文件（蛋白质名称字符串）
    
        # 加载已知复合物，转换为蛋白质名称集合
        known_sets = load_complex_sets(known_file, id_to_gene)
    
        # 加载预测结果，直接得到蛋白质名称集合
        pred_sets = load_pred_set(pred_file)
    
        # 可选过滤：例如排除单节点复合物
        # known_sets = [s for s in known_sets if len(s) >= 3]
        pred_sets = [s for s in pred_sets if len(s) >= 2]
    
        len(known_sets)
        len(pred_sets)
    
        results = evaluate(known_sets, pred_sets, threshold=0.2)
        results_list.append(results)
        print_results(results)
    
    # 汇总结果写入 CSV
    if results_list:
        df = pd.DataFrame(results_list)
        # df.set_index('Folder', inplace=True)   # 文件夹名作为行索引
        output_csv = "evaluation_Indicatos.csv"
        df.to_csv(output_csv)
        print(f"\n汇总结果已保存到 {output_csv}")
        print(df)
    else:
        print("没有找到任何有效的预测结果文件。") 

