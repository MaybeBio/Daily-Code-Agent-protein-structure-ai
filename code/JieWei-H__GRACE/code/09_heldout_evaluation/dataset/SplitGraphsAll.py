import networkx as nx
import os
import pickle
import gc

def save_graph_chunks(graph_list, chunk_size=1000000, idx = 0,name = None,output_dir="Pretrain-Subgraph"):
    """
    将大型图列表分割并保存为pkl文件，及时释放内存
    
    :param graph_list: 包含所有图的原始列表
    :param chunk_size: 每个分割块的大小（默认100万）
    :param output_dir: 输出目录
    """
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    total_graphs = len(graph_list)
    num_chunks = (total_graphs + chunk_size - 1) // chunk_size  # 向上取整
    
    print(f"Starting to process {total_graphs} graphs ({num_chunks} chunks)")
    
    for i in range(num_chunks):
        start_idx = i * chunk_size
        end_idx = min((i + 1) * chunk_size, total_graphs)
        
        # 分割当前块
        chunk = graph_list[start_idx:end_idx]
        
        # 构建文件名
        filename = os.path.join(output_dir, f"{name}_{i+idx*10}.pkl")
        
        # 保存为pkl
        with open(filename, 'wb') as f:
            pickle.dump(chunk, f)
        
        print(f"Saved chunk {i} ({len(chunk)} graphs) to {filename}")
        
        # 及时释放内存
        del chunk
        gc.collect()  # 强制垃圾回收
        
    
    print(f"\nAll chunks saved to {output_dir}")
    print(f"Total chunks: {num_chunks}, Last chunk size: {len(graph_list[(num_chunks-1)*chunk_size:])}")

# 使用示例
if __name__ == "__main__":
    ## 复合物噪声图
    
    for i in range(2):
        # if i<=2:
        #     continue
        print("读取图信息")
        # file_name = os.path.join(f)
        with open(f'all_complex_part{i+1}.pkl', 'rb') as f:
            all_noisy_subgraphs = pickle.load(f)
        print("切割图集合")
        # 执行分割保存
        save_graph_chunks(all_noisy_subgraphs, 1000000,i, "all_noisy_subgraphs")
        
        print("切割完成")
        # 建议：在函数调用后删除原始列表释放内存
        del all_noisy_subgraphs
        gc.collect()

    print("完成全部分割处理！")
