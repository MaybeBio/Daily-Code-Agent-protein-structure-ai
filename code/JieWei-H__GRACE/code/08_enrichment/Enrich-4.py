import pandas as pd
from gprofiler import GProfiler
import os
import numpy as np

# ==========================================
# 配置参数
# ==========================================
organism = "hsapiens"
p_threshold = 0.05
p_extreme = 0.01
min_genes = 2
sources = ["GO:BP", "GO:CC", "GO:MF", "KEGG"]

# 代理配置（如需请取消注释）
os.environ['http_proxy'] = 'http://127.0.0.1:7890'
os.environ['https_proxy'] = 'http://127.0.0.1:7890'

# ==========================================
# 主函数
# ==========================================
def run_enrichment_analysis(input_file, output_stats):
    gp = GProfiler(return_dataframe=True)

    df_input = pd.read_csv(input_file)
    complex_ids = df_input.iloc[:, 0].tolist()
    protein_strings = df_input.iloc[:, 1].tolist()

    total = len(complex_ids)
    print(f"共读取 {total} 个复合物。")

    results = []

    for idx, (cid, proteins) in enumerate(zip(complex_ids, protein_strings)):
        print(f"正在处理 [{idx+1}/{total}]: {cid}...")
        gene_list = [g.strip() for g in proteins.split(',')]

        if len(gene_list) < min_genes:
            row_dict = {'complex_id': cid}
            for src in sources:
                row_dict[src] = np.nan
            results.append(row_dict)
            continue

        try:
            # 根据您提供的参数列表调用 profile
            res = gp.profile(
                organism=organism,
                sources=sources,
                query=gene_list,
                no_evidences=False,          # 若要与 R 完全一致（不返回证据列）请改为 True
                all_results=True,             # 关键：返回所有结果（等效于 R 的 significant=FALSE）
                user_threshold=p_threshold,   # 可保留，但被 all_results 覆盖
                # significance_threshold_method='fdr'  # 可选，根据需要调整
            )

            row_dict = {'complex_id': cid}

            if res is not None and not res.empty:
                for src in sources:
                    src_res = res[res['source'] == src]
                    if not src_res.empty:
                        min_p = src_res['p_value'].min()
                        row_dict[src] = min_p
                    else:
                        row_dict[src] = np.nan
            else:
                for src in sources:
                    row_dict[src] = np.nan

            results.append(row_dict)

        except Exception as e:
            print(f"  - {cid}: 查询出错! 错误信息: {e}")
            row_dict = {'complex_id': cid}
            for src in sources:
                row_dict[src] = np.nan
            results.append(row_dict)

    pval_matrix = pd.DataFrame(results)
    pval_matrix.set_index('complex_id', inplace=True)

    stats_list = []
    for src in sources:
        pvals = pval_matrix[src].dropna()
        num_valid = len(pvals)
        num_sig = sum(pvals < p_threshold) if num_valid > 0 else 0
        num_extreme = sum(pvals < p_extreme) if num_valid > 0 else 0

        stats_list.append({
            'Source': src,
            '#PC': total,
            '#PC of extremely significance': f"{num_extreme} ({num_extreme/total*100:.2f}%)",
            '#PC of significance': f"{num_sig} ({num_sig/total*100:.2f}%)"
        })

    result_table = pd.DataFrame(stats_list)
    print("\n统计结果：")
    print(result_table.to_string(index=False))

    result_table.to_csv(output_stats, index=False, encoding='utf-8-sig')
    print(f"\n统计结果已保存至: {output_stats}")



# ==========================================
# 执行脚本
# ==========================================
if __name__ == "__main__":
    input_file = "generation_results-4.csv"  # 你的输入文件名
    output_file = "LLM_Enrichment-4.csv"
    
    if os.path.exists(input_file):
        run_enrichment_analysis(input_file, output_file)
    else:
        print(f"错误: 找不到文件 {input_csv}")
