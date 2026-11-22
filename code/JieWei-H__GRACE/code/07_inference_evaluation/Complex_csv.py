import pickle
import pandas as pd
import networkx as nx

def convert_complex_pkl_to_csv(complex_pkl, mapping_pkl, output_csv=None):
    """
    将包含复合物子图的pkl文件转换为CSV格式。
    
    参数:
        complex_pkl: 输入pkl文件路径，其中每个元素是networkx图，节点为整数ID。
        mapping_pkl: 映射文件，包含token_id_gene对象，提供id_to_gene字典。
        output_csv: 输出CSV文件路径。若为None，则根据输入文件名自动生成（替换.pkl为.csv）。
    """
    # 加载映射
    with open(mapping_pkl, 'rb') as f:
        token_id_gene = pickle.load(f)
    id_to_gene = token_id_gene.id_to_gene

    # 加载复合物子图
    with open(complex_pkl, 'rb') as f:
        subgraphs = pickle.load(f)

    # 转换为蛋白质名称集合，并生成DataFrame
    data = []
    for i, sg in enumerate(subgraphs):
        node_ids = set(sg.nodes())
        protein_names = {id_to_gene[nid] for nid in node_ids if nid in id_to_gene}
        # 按字母排序后拼接为逗号分隔字符串
        proteins_str = ','.join(sorted(protein_names))
        data.append({'complex_id': f'complex_{i}', 'proteins': proteins_str})

    df = pd.DataFrame(data)

    # 确定输出路径
    if output_csv is None:
        output_csv = complex_pkl.replace('.pkl', '.csv')
    df.to_csv(output_csv, index=False)
    print(f"已转换 {len(subgraphs)} 个复合物，结果保存至 {output_csv}")

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
    # 示例用法：请根据实际路径修改
    complex_pkl = "../Graph_init/complex_graphs.pkl"
    mapping_pkl = "token_id_gene.pkl"
    convert_complex_pkl_to_csv(complex_pkl, mapping_pkl, "gold_complex.csv")
    
