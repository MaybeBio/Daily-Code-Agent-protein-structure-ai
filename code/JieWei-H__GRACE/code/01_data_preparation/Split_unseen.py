import pickle
import networkx as nx
import numpy as np

with open('./Complex_Test.pkl', 'rb') as f:
    test_graphs = pickle.load(f)

with open('./train_proteins.pkl', 'rb') as f:
    train_proteins = pickle.load(f)

train_protein_set = set(train_proteins)

def get_members(g):
    if isinstance(g, nx.Graph):
        return set(g.nodes())
    elif isinstance(g, (list, set, tuple)):
        return set(g)
    elif isinstance(g, dict):
        for k in ['nodes', 'members', 'proteins', 'genes']:
            if k in g:
                return set(g[k])

truly_unseen = []
has_overlap  = []

for g in test_graphs:
    members = get_members(g)
    if len(members & train_protein_set) == 0:
        truly_unseen.append(g)
    else:
        has_overlap.append(g)

print(f"完全unseen: {len(truly_unseen)}")
print(f"有重叠:     {len(has_overlap)}")


# ---------- 新增：统计结点数目 ----------
def analyze_node_counts(complex_list, name):
    if not complex_list:
        print(f"{name} 列表为空，无法统计")
        return
    node_counts = [len(get_members(g)) for g in complex_list]
    mean_val = np.mean(node_counts)
    median_val = np.median(node_counts)
    print(f"\n{name}:")
    print(f"  平均节点数: {mean_val:.2f}")
    print(f"  中位数节点数: {median_val:.2f}")
    print(f"  最小值: {min(node_counts)}")
    print(f"  最大值: {max(node_counts)}")

analyze_node_counts(truly_unseen, "完全unseen复合物")
analyze_node_counts(has_overlap, "有重叠复合物")



with open('./Test_truly_unseen.pkl', 'wb') as f:
    pickle.dump(truly_unseen, f)

with open('./Test_has_overlap.pkl', 'wb') as f:
    pickle.dump(has_overlap, f)

print("已保存: Test_truly_unseen.pkl / Test_has_overlap.pkl")
