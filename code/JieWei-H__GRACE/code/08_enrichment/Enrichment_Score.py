import pandas as pd
from gprofiler import GProfiler
import os
import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed
import math
from tqdm import tqdm

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

# 并行分块数（可修改）
num_chunks = 20

def process_chunk(chunk_ids, chunk_proteins, chunk_index):
    """处理一个数据块的函数，返回该块的results列表"""
    from tqdm import tqdm  # 子进程也需要导入tqdm
    gp = GProfiler(return_dataframe=True)
    results_chunk = []
    total_in_chunk = len(chunk_ids)
    for idx, (cid, proteins) in enumerate(zip(chunk_ids, chunk_proteins)):
        tqdm.write(f"Chunk {chunk_index}: 正在处理 [{idx+1}/{total_in_chunk}] {cid}...")  # 改用tqdm.write避免干扰进度条
        gene_list = [g.strip() for g in proteins.split(',')]

        if len(gene_list) < min_genes:
            row_dict = {'complex_id': cid}
            for src in sources:
                row_dict[src] = np.nan
            results_chunk.append(row_dict)
            continue

        try:
            res = gp.profile(
                organism=organism,
                sources=sources,
                query=gene_list,
                no_evidences=False,
                all_results=True,
                user_threshold=p_threshold,
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

            results_chunk.append(row_dict)

        except Exception as e:
            tqdm.write(f"Chunk {chunk_index}: {cid} 查询出错! 错误信息: {e}")
            row_dict = {'complex_id': cid}
            for src in sources:
                row_dict[src] = np.nan
            results_chunk.append(row_dict)

    return results_chunk

def run_enrichment_analysis(input_file, output_stats, num_chunks=1):
    df_input = pd.read_csv(input_file)
    complex_ids = df_input.iloc[:, 0].tolist()
    protein_strings = df_input.iloc[:, 1].tolist()
    total = len(complex_ids)
    print(f"共读取 {total} 个复合物，将分成 {num_chunks} 块并行处理。")

    # 将数据分成 num_chunks 块
    chunk_size = math.ceil(total / num_chunks)
    chunks = []
    for i in range(num_chunks):
        start = i * chunk_size
        end = min((i + 1) * chunk_size, total)
        if start < total:
            chunks.append((complex_ids[start:end], protein_strings[start:end], i+1))

    all_results = []
    with ProcessPoolExecutor(max_workers=num_chunks) as executor:
        futures = [executor.submit(process_chunk, ids, prots, idx) for ids, prots, idx in chunks]
        # 使用tqdm显示块级进度
        for future in tqdm(as_completed(futures), total=len(futures), desc="处理进度"):
            try:
                chunk_results = future.result()
                all_results.extend(chunk_results)
            except Exception as e:
                tqdm.write(f"一个块处理失败: {e}")

    # 构建pval_matrix
    pval_matrix = pd.DataFrame(all_results)
    pval_matrix.set_index('complex_id', inplace=True)

    # 统计部分（与原来相同）
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

    # 保存详细p值结果
    base, ext = os.path.splitext(output_stats)
    detailed_output = base + '_details' + ext
    pval_matrix.reset_index().to_csv(detailed_output, index=False, encoding='utf-8-sig')
    print(f"详细p值结果已保存至: {detailed_output}")

if __name__ == "__main__":
    input_file = "generation_results-100.csv"  # 你的输入文件名
    output_file = "LLM_Enrichment.csv"
    
    if os.path.exists(input_file):
        run_enrichment_analysis(input_file, output_file, num_chunks=num_chunks)
    else:
        print(f"错误: 找不到文件 {input_file}")
