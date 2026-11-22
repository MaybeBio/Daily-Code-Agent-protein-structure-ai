import pandas as pd
import numpy as np
import random
from itertools import combinations

# 设置随机种子以保证可重复性
random.seed(20030201)
np.random.seed(20030201)

def build_ppi_dataset(input_file, output_file, ratio=(1, 5, 10)):
    """
    从输入CSV构建复合物vs普通PPI vs非PPI数据集
    :param input_file: 原始PPI文件路径，包含列['protein1','protein2','edge_id','type']
    :param output_file: 输出文件路径
    :param ratio: 复合物:普通PPI:非PPI的比例，默认1:5:10
    """
    # 读取数据
    df = pd.read_csv(input_file, sep=',')  # 根据实际分隔符调整，示例是制表符
    print(f"原始数据大小: {len(df)}")
    
    # 分离复合物和普通PPI
    complex_df = df[df['type'] == 'complex'].copy()
    normal_df = df[df['type'] == 'normal'].copy()
    
    n_complex = len(complex_df)
    n_normal_total = len(normal_df)
    
    print(f"复合物PPI数量: {n_complex}")
    print(f"普通PPI总数: {n_normal_total}")
    
    # 目标数量：复合物全部保留，普通和非PPI按比例采样
    target_normal = int(n_complex * ratio[1] / ratio[0])
    target_non = int(n_complex * ratio[2] / ratio[0])
    
    # 如果普通PPI不足，则全部保留
    if target_normal > n_normal_total:
        print(f"普通PPI不足（需要{target_normal}，实际{n_normal_total}），全部保留")
        sampled_normal = normal_df
    else:
        sampled_normal = normal_df.sample(n=target_normal, random_state=42)
    
    print(f"采样后普通PPI数量: {len(sampled_normal)}")
    
    # 构建现有PPI集合（用于去重生成非PPI）
    existing_ppi = set()
    for _, row in df.iterrows():
        p1, p2 = row['protein1'], row['protein2']
        # 存储为有序元组，避免方向重复
        if p1 < p2:
            existing_ppi.add((p1, p2))
        else:
            existing_ppi.add((p2, p1))
    
    # 获取所有蛋白质列表
    all_proteins = set(df['protein1']).union(set(df['protein2']))
    all_proteins = list(all_proteins)
    print(f"总蛋白质种类数: {len(all_proteins)}")
    
    # 生成非PPI样本
    def generate_non_ppi(target_count, existing_set, protein_list, max_attempts=10000000):
        """
        随机生成不重复的非互作蛋白质对
        """
        non_ppi = []
        attempts = 0
        while len(non_ppi) < target_count and attempts < max_attempts:
            p1, p2 = random.sample(protein_list, 2)
            if p1 < p2:
                key = (p1, p2)
            else:
                key = (p2, p1)
            if key not in existing_set:
                non_ppi.append(key)
                existing_set.add(key)  # 加入集合以避免后续重复
            attempts += 1
            if attempts % 100000 == 0:
                print(f"已生成{len(non_ppi)}个非PPI，尝试次数{attempts}")
        if len(non_ppi) < target_count:
            print(f"警告：仅生成{len(non_ppi)}个非PPI，未达到目标{target_count}")
        return non_ppi
    
    non_ppi_pairs = generate_non_ppi(target_non, existing_ppi, all_proteins)
    non_ppi_df = pd.DataFrame(non_ppi_pairs, columns=['protein1', 'protein2'])
    non_ppi_df['edge_id'] = non_ppi_df['protein1'] + '_' + non_ppi_df['protein2']
    non_ppi_df['type'] = 'non_ppi'
    print(f"生成非PPI数量: {len(non_ppi_df)}")
    
    # 合并三个数据集
    final_df = pd.concat([
        complex_df,
        sampled_normal,
        non_ppi_df
    ], ignore_index=True)
    
    # 输出统计
    print("\n最终数据集组成:")
    print(final_df['type'].value_counts())
    print(f"总样本数: {len(final_df)}")
    
    # 保存为CSV（与输入格式一致）
    final_df.to_csv(output_file, sep=',', index=False)
    print(f"已保存到: {output_file}")

if __name__ == "__main__":
    # 使用示例（请根据实际文件路径修改）
    input_file = "final_ppi_network.csv"   # 输入文件路径
    output_file = "sampled_ppi_data.csv"  # 输出文件路径
    build_ppi_dataset(input_file, output_file, ratio=(1, 1, 1))
