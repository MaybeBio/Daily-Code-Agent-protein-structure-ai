import pickle
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.optimize import linear_sum_assignment  # 如果可用

# ---------- 评估函数（从 Eval.py 复制，略作调整）----------
def load_complex_sets(pkl_file, id_to_gene):
    with open(pkl_file, 'rb') as f:
        subgraphs = pickle.load(f)
    sets = []
    for sg in subgraphs:
        node_ids = set(sg.nodes())
        protein_names = {id_to_gene[nid] for nid in node_ids if nid in id_to_gene}
        sets.append(protein_names)
    return sets

def compute_mmr(set_a, set_b):
    intersection = len(set_a & set_b)
    return (intersection ** 2) / (len(set_a) * len(set_b)) if len(set_a) and len(set_b) else 0.0

def greedy_matching(known_sets, pred_sets, threshold=0.2):
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
        row_ind, col_ind = linear_sum_assignment(-weights)
        total_weight = weights[row_ind, col_ind].sum()
    except ImportError:
        print("警告: scipy未安装，使用贪心近似计算全局MMR")
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
    n_known = len(known_sets)
    n_pred = len(pred_sets)
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
    mmr_matrix = np.zeros((n_known, n_pred))
    for i, ks in enumerate(known_sets):
        for j, ps in enumerate(pred_sets):
            mmr_matrix[i, j] = compute_mmr(ks, ps)
    P_gc = 0
    G_pc = 0
    for j in range(n_pred):
        if any(mmr_matrix[i, j] >= threshold for i in range(n_known)):
            P_gc += 1
    for i in range(n_known):
        if any(mmr_matrix[i, j] >= threshold for j in range(n_pred)):
            G_pc += 1
    precision = P_gc / n_pred if n_pred > 0 else 0.0
    recall = G_pc / n_known if n_known > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    global_mmr = compute_global_mmr(known_sets, pred_sets)
    greedy_matches = greedy_matching(known_sets, pred_sets, threshold)
    mean_mmr_greedy = np.mean([mmr for _, _, mmr in greedy_matches]) if greedy_matches else 0.0
    metrics = {
        'P_gc': P_gc,
        'G_pc': G_pc,
        'Precision': precision,
        'Recall': recall,
        'F1': f1,
        'Global_MMR': global_mmr,
        'Mean_MMR': mean_mmr_greedy,
    }
    return {**stats, **metrics}

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

# ---------- 主程序 ----------
if __name__ == "__main__":
    # 请根据实际路径修改以下三个变量
    mapping_file = "token_id_gene.pkl"               # 映射文件
    known_file = "../Graph_init/complex_graphs.pkl"  # 已知复合物子图文件
    pred_file = "generation_results-100.pkl"         # 您已生成的完整预测结果文件

    # 加载映射
    with open(mapping_file, 'rb') as f:
        token_id_gene = pickle.load(f)
    id_to_gene = token_id_gene.id_to_gene

    # 加载已知复合物（转换为蛋白质名称集合），并过滤掉大小 < 3 的
    known_sets = load_complex_sets(known_file, id_to_gene)
    print(f"加载已知复合物 {len(known_sets)} 个")

    # 加载完整预测结果
    with open(pred_file, 'rb') as f:
        pred_results = pickle.load(f)

    # 按 prompt_id 排序（确保顺序对应重要性降序）
    pred_results.sort(key=lambda x: x['prompt_id'])

    # 提取所有预测复合物的蛋白质集合
    all_pred_sets_raw = [set(res['sft_response'].split()) for res in pred_results]
    N_total = len(all_pred_sets_raw)
    print(f"加载预测复合物原始数量: {N_total}")

    # 定义百分比列表
    percentages = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    results_list = []

    for p in percentages:
        k = int(N_total * p / 100)
        k = max(1, min(k, N_total))  # 至少取1个
        pred_sets_sub_raw = all_pred_sets_raw[:k]
        # 过滤掉大小 < 2 的复合物（如空或单节点）
        pred_sets_sub = [s for s in pred_sets_sub_raw if len(s) >= 2]
        print(f"百分比 {p}%: 取前 {k} 个，过滤后 {len(pred_sets_sub)} 个复合物")

        metrics = evaluate(known_sets, pred_sets_sub, threshold=0.2)
        metrics['percentage'] = p
        metrics['used_pred_count'] = len(pred_sets_sub)
        metrics['original_pred_count'] = k
        results_list.append(metrics)

    # 保存汇总结果到 CSV
    df = pd.DataFrame(results_list)
    output_csv = "evaluation_by_percentage.csv"
    df.to_csv(output_csv, index=False)
    print(f"\n汇总结果已保存到 {output_csv}")
    print(df[['percentage', 'original_pred_count', 'used_pred_count',
              'Precision', 'Recall', 'F1', 'Global_MMR', 'Mean_MMR']])
