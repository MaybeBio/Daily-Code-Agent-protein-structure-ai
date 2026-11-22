import pandas as pd
import numpy as np

def load_annotation_matrix(file_path, sep=','):
    """
    读取注释矩阵（基因×注释项），返回DataFrame，基因名为索引，值为0/1
    假设第一列为基因名，其余列为注释项，单元格为1表示有注释，0表示无
    """
    df = pd.read_csv(file_path, sep=sep, index_col=0)
    # 确保值为数值0/1（如果原始是布尔或字符串，转换为0/1）
    df = df.astype(int)
    return df

def split_go_by_aspect(go_matrix, aspect_file, sep=','):
    """
    根据aspect文件将GO矩阵拆分为多个子矩阵
    go_matrix: DataFrame，索引为基因，列为GO term描述
    aspect_file: 包含两列 'Aspect' 和 'Function'，Function与go_matrix的列名一致
    返回字典 {aspect: DataFrame}，每个DataFrame只包含该aspect的列
    """
    # 读取aspect映射
    aspect_df = pd.read_csv(aspect_file, sep=sep)
    # 构建 term -> aspect 字典
    term_to_aspect = dict(zip(aspect_df['Function'], aspect_df['Aspect']))
    
    # 按aspect分组列名
    aspect_columns = {}
    for term in go_matrix.columns:
        asp = term_to_aspect.get(term)
        if asp is None:
            print(f"警告：GO term '{term}' 未在分级文件中找到，已忽略")
            continue
        aspect_columns.setdefault(asp, []).append(term)
    
    # 为每个aspect构建子矩阵
    aspect_matrices = {}
    for asp, cols in aspect_columns.items():
        aspect_matrices[asp] = go_matrix[cols]
    return aspect_matrices

def compute_shared_terms_vectorized(ppi_df, matrix, gene_to_idx):
    """
    向量化计算PPI对共享注释数
    ppi_df: DataFrame，必须包含'protein1'和'protein2'列
    matrix: numpy数组，形状为 (n_genes, n_terms)，行顺序与gene_to_idx一致
    gene_to_idx: 字典 {gene: row_index}
    返回numpy数组，长度为len(ppi_df)
    """
    # 获取两列基因对应的行索引，如果基因不在映射中，索引设为-1
    idx1 = ppi_df['protein1'].map(gene_to_idx).fillna(-1).astype(int)
    idx2 = ppi_df['protein2'].map(gene_to_idx).fillna(-1).astype(int)
    
    # 处理缺失基因：将缺失基因的行向量设为全0
    # 创建一个掩码，标记两个基因都存在的情况
    mask = (idx1 >= 0) & (idx2 >= 0)
    shared = np.zeros(len(ppi_df), dtype=int)
    
    if mask.any():
        # 对于两个基因都存在的行，取出对应的行向量并计算点积
        rows1 = matrix[idx1[mask]]
        rows2 = matrix[idx2[mask]]
        shared[mask] = np.sum(rows1 * rows2, axis=1)
    
    return shared

def main(ppi_file, annotation_files, aspect_file=None, output_file=None):
    """
    ppi_file: PPI数据集CSV，必须包含'protein1','protein2'，可选'type','edge_id'
    annotation_files: 字典 {注释类型: 文件路径}，如 {'subcellular': 'sub.csv', 'go': 'go.csv', 'kegg': 'kegg.csv'}
    aspect_file: GO分级文件路径（如果'go'在annotation_files中则必须提供）
    output_file: 输出特征CSV路径
    """
    # 读取PPI数据
    ppi_df = pd.read_csv(ppi_file)
    print(f"PPI样本数: {len(ppi_df)}")
    
    # 保存原始标识列
    features_df = ppi_df[['protein1', 'protein2']].copy()
    if 'edge_id' in ppi_df.columns:
        features_df['edge_id'] = ppi_df['edge_id']
    if 'type' in ppi_df.columns:
        features_df['type'] = ppi_df['type']
    
    # 处理每个注释文件
    for anno_name, anno_file in annotation_files.items():
        print(f"处理 {anno_name} 注释...")
        matrix_df = load_annotation_matrix(anno_file)
        
        # 构建基因到行索引的映射（所有基因，包括可能不在PPI中的）
        gene_to_idx = {gene: i for i, gene in enumerate(matrix_df.index)}
        
        # 如果是GO且有aspect文件，则拆分并分别处理
        if anno_name.lower() == 'go' and aspect_file is not None:
            aspect_matrices = split_go_by_aspect(matrix_df, aspect_file)
            for aspect, sub_matrix_df in aspect_matrices.items():
                # 将子矩阵转为numpy数组，行顺序与gene_to_idx一致
                # 确保sub_matrix_df的行顺序与matrix_df一致（即gene_to_idx的顺序）
                sub_matrix = sub_matrix_df.loc[list(gene_to_idx.keys())].values
                shared = compute_shared_terms_vectorized(features_df, sub_matrix, gene_to_idx)
                feat_name = f"{anno_name}_{aspect}_shared"
                features_df[feat_name] = shared
                print(f"  完成 {feat_name}, 平均共享数: {shared.mean():.2f}")
        else:
            # 非GO或未拆分，直接处理
            matrix = matrix_df.loc[list(gene_to_idx.keys())].values
            shared = compute_shared_terms_vectorized(features_df, matrix, gene_to_idx)
            feat_name = f"{anno_name}_shared"
            features_df[feat_name] = shared
            print(f"  完成 {feat_name}, 平均共享数: {shared.mean():.2f}")
    
    # 输出
    if output_file:
        features_df.to_csv(output_file, index=False)
        print(f"特征已保存到 {output_file}")
    else:
        return features_df


# 使用示例
if __name__ == "__main__":
    # 文件路径配置（请根据实际情况修改）
    ppi_file = "sampled_ppi_data.csv"          # 已构建的PPI数据集
    annotation_files = {
        'Subcellular': 'Subcellular_matrix.csv',
        'GO': 'GO_matrix.csv',
        'KEGG': 'KEGG_matrix.csv'
    }
    aspect_file = "GO.csv"      # 包含Aspect和Function两列的文件
    output_file = "ppi_annotation_features.csv"
    
    main(ppi_file, annotation_files, aspect_file, output_file)
